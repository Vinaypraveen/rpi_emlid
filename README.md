INSTALL REQUESTS, simplekml, PANDAS $ MATPLOTLIB SOCKETIO GIT gfortran

sudo apt install python3-pip -y
sudo apt install git -y

pip install simplekml --break-system-packages

sudo apt install python3-pandas python3-matplotlib python3-requests python3-websocket python3-socketio python3-flask gfortran -y

------------------------------------------------------------------------------

INSTALL RTKLIB

git clone https://github.com/rtklibexplorer/RTKLIB.git

convbin : to convert UBX to Rinex files
cd RTKLIB/app/consapp/convbin/gcc
make
sudo make install

rnx2rtkp : to process rinex files to generate .pos and events.pos files
cd RTKLIB/app/consapp/rnx2rtkp/gcc
make
sudo make install

below is the format for convbin & rnx2rtkp command usage (and use the conf file) :

convbin '/home/vinlee/Desktop/Reach_raw_20241001051153.UBX' -r ubx -o '/home/vinlee/Desktop/Reach_raw_20241001051153/file.24O' -n '/home/vinlee/Desktop/Reach_raw_20241001051153/file.24N'


rnx2rtkp -k '/home/vinlee/Downloads/test folder/emlid_rpi.conf' -o '/home/vinlee/Downloads/test folder/output.pos' '/home/vinlee/Downloads/test folder/Reach_raw_20241105094352_RINEX_3_04/Reach_raw_20241105094352.24O' '/home/vinlee/Downloads/test folder/Reach_raw_20241105094352_RINEX_3_04/Reach_raw_20241105094352.24P'

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

PYTHON CODE ON BOOT IN RASPBERRY PI

METHOD 1 : open a terminal on desktop and run

!) Edit the ~/.bashrc File

nano ~/.bashrc

2) Add the Following at the End of the File:

if [ "$(tty)" = "/dev/tty1" ]; then
    lxterminal -e "python3 /home/pi/Desktop/H30/final_code.py"
fi

3) sudo reboot

------------

METHOD 2 : simply run inside the rc.local file

1) Edit the rc.local file:

sudo nano /etc/rc.local

2) Add the command to run your Python script before the exit 0 line:

python3 /home/pi/Desktop/H30/final_code.py &

3) sudo reboot

------------
Either ways if you want to stop the script midway you can use following steps

1) Find the Process ID (PID) of the Running Script: the PID (Process ID) is the second column in each row

ps aux | grep final_code.py

2) Kill the Process:

kill -9 <PID>

EXAMPLE :
vinlee      1701  0.2  1.0 542340 39108 tty1     Rl+  21:20   0:00 lxterminal -e python3
/home/vinlee/Desktop/H30/final_code.py
vinlee      1710  1.9  2.6 399708 104484 pts/0   Ssl+ 21:20   0:07 python3 /home/vinlee/Desktop/H30/final_code.py

kill -9 1710


------------------------------------------------------------------------------
example on rpi zero 2w

username : vinlee
password : 1234

sudo apt-get update && sudo apt-get upgrade -y && sudo apt install python3-pip git -y && sudo pip install simplekml --break-system-packages && sudo apt install python3-pandas python3-matplotlib python3-requests python3-websocket python3-socketio python3-flask gfortran dhcpcd5 -y && git clone https://github.com/rtklibexplorer/RTKLIB.git

cd RTKLIB/app/consapp/convbin/gcc
make
sudo make install
cd
cd RTKLIB/app/consapp/rnx2rtkp/gcc
make
sudo make install

sudo nano /boot/firmware/config.txt
dtoverlay=w5500 (at the end of config.txt only for rpi zero and zero 2w)
sudo modprobe w5100_spi


sudo nano /etc/dhcpcd.conf
---------
interface eth0
static ip_address=192.168.144.20/24
static routers=192.168.144.1
static domain_name_servers=168.126.63.1 168.126.63.2
---------
sudo systemctl restart dhcpcd


copy the emlid_rpi.conf file into the /home/vinlee path
cp /media/vinlee/EMLID_LOGS/emlid_rpi.conf /home/vinlee  (.conf file path - /home/vinlee/emlid_rpi.conf)

sudo nano final.py (paste the final code)

sudo reboot

------------------------------------------------------------------------------
example on rpi 4

username : vinlee
password : 1234

copy the emlid_rpi.conf file using the below command
cp /media/vinlee/EMLID_LOGS/emlid_rpi.conf /home/vinlee

Run the dependencies script:
sudo apt install dos2unix
dos2unix /media/vinlee/EMLID_LOGS/pilid_dependencies.sh
sudo bash /media/vinlee/EMLID_LOGS/pilid_dependencies.sh

sudo nano final.py (paste the final code)

sudo reboot
