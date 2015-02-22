#!/bin/env python
#Copyright (C) 2015 Richard Owen, rowen@ieee.org
#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License
#along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import getpass
import sys
import os
import os.path
import subprocess
import shutil
import time
verbose = False
null_file = None
args = None
def parse_arguments():
  rows, columns = os.popen('stty size', 'r').read().split()
  parser = argparse.ArgumentParser(prog="mkdiskimage.py", formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=50,width=int(columns)))
  parser.add_argument("--preloader", help="path to preloader image", type=str)
  parser.add_argument("--bootloader", help="path to bootloader image", type=str)
  parser.add_argument("--loadersize", help="size of the preloader and boot loader partition in mebibytes", type=int, default=16)
  parser.add_argument("--loadernumber", help="partition number of the loader partition", type=int,default=3, choices=[1,2,3,4])
  parser.add_argument("--fat32size", help="size of the fat32 partition in mebibytes", type=int, default=100)
  parser.add_argument("--fat32number", help="partition number of the fat32 partition", type=int, default=1, choices=[1,2,3,4])
  parser.add_argument("--rootfssize", help="size of the linux rootfs partition in mebibytes; 0 fills the image", type=int, default=0)
  parser.add_argument("--rootfsnumber",help="partition number of the rootfs partition", type=int, default=2, choices=[1,2,3,4])
  parser.add_argument("--imagesize", help="total size of the disk image in mebibytes", type=int, default=2048)
  parser.add_argument("--images", help="comma delimited list of images to be added to the boot loader's fat32 partition", type=str)
  parser.add_argument("--rootfsimage", help="path to the compressed root file system. Should be in in a compressed tarball format", type=str)
  parser.add_argument("--rootfstype", help="file system to use for the root fs", type=str, default="ext3",choices=["ext2","ext3","ext4", "btrfs", "xfs"])
  parser.add_argument("--loopdevice",help="starting point for loopback devices", type=int, default=0)
  parser.add_argument("--outfile", help="name of the resulting disk image", type=str, default = "./diskimage.img")
  parser.add_argument("--sector_size", help="sector size of the device in bytes.", type=int, default=512, choices=[512,1024,2048,4096,8192])
  output_group = parser.add_mutually_exclusive_group()
  output_group.add_argument("--verbose", help="enables additional feedback", action="store_true")
  output_group.add_argument("--quiet", help="removes all feedback", action="store_true")
  replace_group = parser.add_mutually_exclusive_group()
  replace_group.add_argument("--overwrite", help="if outfile already exists, overwrite it with a new one", action="store_true")
  replace_group.add_argument("--replace", help="Replace only specified sections of an existing image", action="store_true")
  args = parser.parse_args()
  return args

def info(message):
  if args.verbose:
    print message

def warn(message):
  print message

def print_partition_summary(total_size, slack_size):
  print "Fat32 size:\t{0}MiB".format(args.fat32size)
  print "Loader size:\t{0}MiB".format(args.loadersize)
  print "RootFS size:\t{0}MiB".format(args.rootfssize)
  print "Total Size:\t{0}MiB".format(total_size)
  print "Image size:\t{0}MiB".format(args.imagesize)
  print "Slack:\t\t{0}MiB".format(slack_size)
  if (slack_size) < 0:
    warn("Slack size of {0} is < 0MiB, cannot proceed".format(slack_size))
    sys.exit(-1)
  return -1

def print_partition_sizes(partition_list):
  print "<Partition>\t<Start>\t\t<Size>\t\t<End>"
  for i in xrange(0,len(partition_list)):
    print "P{0}:\t\t{1}\t\t{2}\t\t{3}".format(str(i),str(partition_list[i][0]), str(partition_list[i][1] + 1), str(partition_list[i][0]+partition_list[i][1]))

def compute_partition_sizes():
  info("computing partition sizes")
  reserved = 1 #lower 1MiB is reserved
  total_size = args.loadersize + args.fat32size + args.rootfssize
  slack_size = args.imagesize - total_size - reserved
  #handle cases where a particular rootfs size is not specified
  if args.rootfssize == 0 and slack_size > 0:
    args.rootfssize = slack_size
    slack_size = 0
    total_size = args.loadersize + args.fat32size + args.rootfssize + reserved
  return (total_size, slack_size)

def compute_partition_boundaries():
  info("computing partition boundaries")
  partitions = [[0 for x in range(5)] for x in range(3)] #[<partition number, <partition start>, <partition span>, <partition size>, <partition type>]
  partitions[0][0] = args.fat32number
  partitions[0][3] = args.fat32size
  partitions[0][4] = 0x0C
  partitions[1][0] = args.rootfsnumber
  partitions[1][3] = args.rootfssize
  partitions[1][4] = 0x83
  partitions[2][0] = args.loadernumber
  partitions[2][3] = args.loadersize
  partitions[2][4] = 0xA2
  sectors_per_mib = 1048576 / args.sector_size
  start_sector = 1 * sectors_per_mib  #lower 1MiB is reserved
  for i in range(len(partitions)):    #iterate over the partitions in the order that they are stored in the list
    for j in range(len(partitions)):  #iterate over the partitions in the order that they are specified by the user
      if partitions[j][0] == i + 1:
        partitions[j][1] = start_sector
        partitions[j][2] = (partitions[j][3] * sectors_per_mib) - 1
        start_sector = start_sector + (partitions[j][3] * sectors_per_mib)
  partition_list = [[0 for x in range(3)] for x in range(3)] #[<partition starting sector>, <partition span in sectors>, <partition type>]
  for i in range(len(partitions)):    #reorder the partitions into a the order that they will appear on the disk, include just the starting sector, span, and type
    j = partitions[i][0] - 1
    partition_list[j][0] = partitions[i][1]
    partition_list[j][1] = partitions[i][2]
    partition_list[j][2] = partitions[i][4]
  return partition_list

def create_partitions(partition_list):
  fdisk_command = ["fdisk"]
  fdisk_args = ["-b {0}".format(args.sector_size), "/dev/loop" + str(args.loopdevice)]
  fdisk_string = fdisk_command + fdisk_args
  #create the partitions
  command_string = "o\nn\np\n1\n{0}\n+{1}\nn\np\n2\n{2}\n+{3}\nn\np\n3\n{4}\n+{5}\n".format(str(partition_list[0][0]),str(partition_list[0][1]),str(partition_list[1][0]),str(partition_list[1][1]),str(partition_list[2][0]),str(partition_list[2][1]))
  #set the partition types
  command_string = command_string + "t\n1\n{0}\nt\n2\n{1}\nt\n3\n{2}\n".format(hex(partition_list[0][2]), hex(partition_list[1][2]), hex(partition_list[2][2]))
  #write the partition table to the device
  command_string = command_string + "w"
  #execute the subprocess
  info("creating partitions")
  proc = subprocess.Popen(fdisk_string, stdin=subprocess.PIPE)
  proc.stdin.write(command_string)
  proc.communicate()
  info("refreshing kernel partition table")
  subprocess.call("partprobe")

def create_image_file():
  info("creating image file")
  dd_command = ["dd"]
  dd_args = ["if=/dev/zero","of={0}".format(args.outfile),"bs=1M","count={0}".format(args.imagesize)]
  dd_string = dd_command + dd_args
  subprocess.call(dd_string)

def create_mount_points():
  mount_points = ["img-fat32","img-rootfs"]
  info("creating temporary mount points")
  for i in mount_points:
    if not os.path.exists(i):
      os.makedirs(i)
    else:
      warn("Folder {0} already exists, cannot proceed.".format(i))

def remove_mount_points():
  mount_points = ["img-fat32", "img-rootfs"]
  info("removing temporary mount points")
  for i in mount_points:
    if os.path.exists(i):
      os.rmdir(i)

def mount_filesystems():
  mount_command = ["mount"]
  mount_points = ["img-fat32", "img-rootfs"]
  mount_devices = ["/dev/loop" + str(args.loopdevice) + "p{}".format(str(args.fat32number)), "/dev/loop" + str(args.loopdevice) + "p{}".format(str(args.rootfsnumber))]
  for i in xrange(0,len(mount_points)):
    mount_args = [mount_devices[i],mount_points[i]]
    mount_string = mount_command + mount_args
    if verbose:
      print "mounting {0} on: {1}".format(mount_devices[i],mount_points[i])
      subprocess.call(mount_string)
    else:
      subprocess.call(mount_string,stdout=null_file)

def unmount_filesystems():
  unmount_command = ["umount"]
  unmount_points = ["img-fat32", "img-rootfs"]
  for i in xrange(0,len(unmount_points)):
    unmount_args = [unmount_points[i]]
    unmount_string = unmount_command + unmount_args
    if verbose:
      print "unmounting: {0}".format(unmount_points[i])
      subprocess.call(unmount_string)
    else:
      subprocess.call(unmount_string,stdout=null_file)

def create_fat32_filesystem(partition_number):
  destination = ["/dev/loop" + str(args.loopdevice) + "p" + str(partition_number)]
  cluster_size = 1024
  sectors_per_cluster = cluster_size / args.sector_size
  mkfs_command = ["mkfs.fat"]
  mkfs_args = ["-F 32","-s {0}".format(max(sectors_per_cluster,1)),"-S {0}".format(args.sector_size)]
  mkfs_string = mkfs_command + mkfs_args + destination
  if verbose:
    print "Creating {0} filesystem on partition {1}".format("fat",partition)
    subprocess.call(mkfs_string)
  else:
    subprocess.call(mkfs_string, stdout=null_file)

def create_rootfs_filesystem(partition_number):
  destination = ["/dev/loop" + str(args.loopdevice) + "p" + str(partition_number)]
  cluster_size = 8192
  sectors_per_cluster = cluster_size / args.sector_size
  mkfs_command = ["mkfs.{0}".format(args.rootfstype)]
  if args.rootfstype in ["ext4"]:
    warn("The ext4 file system uses huge files by default. 32-bit kenels must be compiled with CONFIG_LBDAF")
  if args.rootfstype not in ["ext2","ext3","ext4"]:
    warn("The rootfs filesystem that you have chosen: {0} is often not enabled by default on embedded system kernels. Please make sure that your kernel has support for this file system enabled".format(args.rootfstype))
  mkfs_args = []
  mkfs_string = mkfs_command + mkfs_args + destination
  if verbose:
    print "Creating {0} filesystem on partition {1}".format("ext4",partition)
    subprocess.call(mkfs_string)
  else:
    subprocess.call(mkfs_string, stdout=null_file)

def create_file_systems():
  create_fat32_filesystem(args.fat32number)
  create_rootfs_filesystem(args.rootfsnumber)


def mount_loopback_device():
  losetup_command = ["losetup"]
  losetup_args = ["-P","/dev/loop" + str(args.loopdevice),"{0}".format(args.outfile)]
  losetup_string = losetup_command + losetup_args
  if verbose:
    print "mounting loopback device"
    subprocess.call(losetup_string)
  else:
    subprocess.call(losetup_string, stdout=null_file)

def clean_loopback_devices():
  losetup_command = ["losetup"]
  losetup_args = ["-D"]
  losetup_string = losetup_command + losetup_args
  if verbose:
    print "cleaning up loopback devices"
    subprocess.call(losetup_string)
  else:
    subprocess.call(losetup_string, stdout=null_file)

def install_preloader(partition_number):
  dd_command = ["dd"]
  destination = "/dev/loop" + str(args.loopdevice) + "p" + str(partition_number + 1)
  dd_args = ["if={0}".format(args.preloader),"of={0}".format(destination),"bs=1k","count=256"]
  dd_string = dd_command + dd_args
  if verbose:
    print "installing preloader to: {0}".format(destination)
    proc = subprocess.call(dd_string)
  else:
    proc = subprocess.call(dd_string,stdout=null_file)

def install_bootloader(partition_number):
  dd_command = ["dd"]
  destination = "/dev/loop" + str(args.loopdevice) + "p" + str(partition_number + 1)
  dd_args = ["if={0}".format(args.bootloader),"of={0}".format(destination),"bs=1k","count=768","seek=256"]
  dd_string = dd_command + dd_args
  if verbose:
    print "installing bootloader to: {0}".format(destination)
    proc = subprocess.call(dd_string)
  else:
    proc = subprocess.call(dd_string,stdout=null_file)

def install_fat32_images(mount):
  files = args.images.split(",")
  for i in files:
    if verbose:
      print "copying file: {0} to: {1}".format(i,mount)
    shutil.copy(os.path.expanduser(i),mount)

def install_rootfs_image(mount):
  tar_command = ["tar"]
  tar_args = ["--extract","--directory={0}".format(mount),"--file={0}".format(args.rootfsimage)]
  tar_string = tar_command + tar_args
  if verbose:
    print "extracting root file system to mount point: {0}".format(mount)
    subprocess.call(tar_string)
  else:
    subprocess.call(tar_string,stdout=null_file)

def main():
  global verbose
  global null_file
  global args
  args = parse_arguments()
  #disable stdout if output is suppressed via --quiet
  if args.quiet:
    null_file = open("/dev/null","w")
    sys.stdout = null_file
  #this script requires root privileges
  user = getpass.getuser()
  if user != "root":
    print "Must be root"
    sys.exit(-1)

  info("Verbose Enabled")
  [total_size, slack_size] = compute_partition_sizes()
  partition_list = compute_partition_boundaries()
  #dismount any existing loopback devices
  clean_loopback_devices()
  #create the image file, or replace it if overwriting is enabled
  if os.path.isfile(args.outfile) and not args.overwrite:
    print "File:{0} already exists. Must specify either --overwrite or --replace".format(args.outfile)
    sys.exit(-1)
  else:
    create_image_file()
  
  print_partition_summary(total_size, slack_size)
  print_partition_sizes(partition_list)
  #mount the newly created loopback device
  mount_loopback_device()
  #if not args.replace:
  if not args.replace:
    create_partitions(partition_list)
    clean_loopback_devices()
    mount_loopback_device()
    #unmount the loopback device and remount it to create devices for the new partitions
  
  
    #create filesystems on the non-raw partitions
  create_file_systems()
  if args.preloader:
    install_preloader(args.loadernumber)
  if args.bootloader:
    install_bootloader(args.loadernumber)

  create_mount_points()
  mount_filesystems()

  if args.images:
    install_fat32_images(os.getcwd() + "/img-fat32/")
  if args.rootfsimage:
    install_rootfs_image(os.getcwd() + "/img-rootfs/")
  time.sleep(1) #Wait a second for file system operations to complete
  unmount_filesystems()
  remove_mount_points()
  clean_loopback_devices()

# Use a main function
if __name__ == "__main__":
  main()
