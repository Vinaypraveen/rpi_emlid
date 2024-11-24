INSTALL SOCKETIO

sudo apt install python3-socketio

sudo apt install python3-websocket

pip install python-socketio --break-system-packages (CHECK WITHOUT THIS LINE FIRST)

------------------------------------------------------------------------------

INSTALL REQUESTS

sudo apt install python3-requests

------------------------------------------------------------------------------

INSTALL RTKLIB

Install Required Dependencies :
sudo apt install build-essential git libncurses5-dev libqt5widgets5 qtbase5-dev qtchooser qt5-qmake qtbase5-dev-tools

Download the package :
git clone https://github.com/tomojitakasu/RTKLIB.git

redirect to rnx2rtkp folder using following command and run make commands to install the rnx2rtkp package on to raspberry pi.

cd RTKLIB/app/rnx2rtkp/gcc
make
sudo make install

below is the format for rnx2rtkp command usage :

rnx2rtkp -p 0 -m 15 -o '/home/vinlee/Downloads/test folder/output.pos' '/home/vinlee/Downloads/test folder/Reach_raw_20241105094352_RINEX_3_04/Reach_raw_20241105094352.24O' '/home/vinlee/Downloads/test folder/Reach_raw_20241105094352_RINEX_3_04/Reach_raw_20241105094352.24P'

------------------------------------------------------------------------------
RASPBERRY PI ZERO 2W W5500 SPI TO ETHERNET MODULE INSTALLATION STEPS

sudo nano /boot/firmware/config.txt

write the below line at the end of config.txt then save and exit and reboot the pi.
dtoverlay=w5500

Activate Device driver module
sudo modprobe w5100_spi

Check whether the driver module has been successfully loaded
lsmod | grep w5100

Check the network interface with the ifconfig -a command
------------------------------------------------------------------------------
STATIC IP ASSIGNMENT

The dhcpcd service may not be installed or is disabled. You can check if it is installed using:
sudo systemctl status dhcpcd

If it’s not installed, you can install it with:
sudo apt install dhcpcd5

Now edit the following file :
sudo nano /etc/dhcpcd.conf

interface eth0
static ip_address=192.168.144.20/24
static routers=192.168.144.1
static domain_name_servers=168.126.63.1 168.126.63.2

To check the connection
ping 192.168.144.1

to restart
sudo systemctl restart dhcpcd

sudo reboot
------------------------------------------------------------------------------

