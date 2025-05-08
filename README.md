# Usage
#### Download page as html
First we need to download the upload page of Slskd as html. In order to do this we will first cascade all users that we want to be counted in the html, uploads that are hidden will not we in the html and therefor not counted in the statistsits
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

