# What is does
Give you the upload stats in a digestable way. Output example:  
```
===== SLSKD TRANSFER STATISTICS =====

Overall Statistics:
Successfully transferred: 18.90 GB (705 files)
Failed transfers: 624.5 MB (20 files)
Total size of all files: 19.53 GB (725 files)
Success rate: 96.8%

File Type Statistics:
FLAC files: 723
MP3 files: 3
Other files: -1

Top Users by Total Transfer Volume:
1. karmapoliceofficer01: 1.57 GB total
2. retardedpirate: 1.12 GB total
3. stalkiii567: 941.5 MB total
4. satanandbabylon: 934.6 MB total
5. Mr Webster: 911.8 MB total

Top Users by Successful Transfers:
1. karmapoliceofficer01: 1.57 GB successful (19 files)
2. retardedpirate: 1.12 GB successful (37 files)
3. stalkiii567: 941.5 MB successful (40 files)
4. satanandbabylon: 934.6 MB successful (22 files)
5. Mr Webster: 911.8 MB successful (40 files)

=====================================
```

# Usage
#### Download page as html
First we need to download the upload page of Slskd as html. In order to do this we will first cascade all users that we want to be counted in the html, uploads that are hidden will not we in the html and therefor not counted in the statistsics  
![cascaded](https://github.com/user-attachments/assets/e17e8b9b-ad32-4fde-9972-61dae944fcb8)

![image](https://github.com/user-attachments/assets/6944add4-4f95-483b-875e-c70e99d0f082)  
This is the context menu on firefox. I believe the option is called "Save As..." on chrome based browsers I did not test the script on a chromium downloaded html.
There are also extensions that i did not test either.

#### Download the python script
The script can be downloaded either from the release or the repo directly
#### Run the Python script with the html file as $1
when running the python script you must give it the html file it needs. for example if I am in the same directopry as both the html file and the script i will type 
```
python slskd-upload-stats.py  slskd.html
```
but it can also be used with absolute paths. Ex:
```
python /home/USER/Scripts/flac/slskd-upload-stats.py  /home/USER/Downloads/slskd.html
```

