Ultra-Meme Chatango CLIent
==========================
Version 6.28318530717
--------------------------
A terminal application written in Python with curses input and ANSI escape-colored output.   
Used to implement a client for chatango, an online chatroom.
Run `python chatango.py` or `./chatango.py` in the directory you extracted it to.  
I recommend making a symlink in /usr/local/bin/ so you don't have to navigate to the folder,
or especially have a million files in `~/`

This client is (used to be) based on [chlib.py](https://github.com/cellsheet/chlib),
and uses [python wcwidth](https://github.com/jquast/wcwidth).

I also have a [custom script](https://puu.sh/EfW7B.py) with more dependencies; namely
livestreamer, youtube-dl, and xclip.

Features:
--------------------------
* (Cyclical) Tab completion
* Live terminal resizing
* Tracking images and links posted (F2)
* View members of a certain room (F3)
* Alter formatting sent to the chatango group (F4)
* Change channel (F5)
	* Supports white, red, and blue channels (and the apparently forgotten "both" channel)
* Colorized and filtered output
	* Color text matching a regex or filter messages based on conditions
* Client commands
	* Type \`help while the input box is empty to display a list of commands implemented
* Mouse support
* Ctrl-f substring searching and reply accumulation
	* Jumping to found messages


Dependencies:
--------------------------
* Python 3
* Python ncurses (included on most distros, Python cygwin)

Optional: (see below for changing)
* Feh image viewer
* MPV


Changing default openers:
--------------------------
If you want to use some other program like ImageMagick to open images,
you'll have to do the following in a custom file
```
from client import linkopen
linkopen.IMG_ARGS = ["animate", ...]
```
Where ... represents more command line arguments. Similarly can be done 
to replace mpv (using `MPV_ARGS`).


Adding custom modules:
--------------------------
On startup, the path `~/.cubecli` is created to contain persistent data such as
username, room name, and options. The directory `~/.cubecli/custom` is also added
to contain modules. Unless the `-nc` option is specified, all modules in the
folder are imported. This is where the above-mentioned script comes in.


Windows (Cygwin):
-----------------
The Python installation under cygwin works mostly fine for input
and drawing within MinTTY, the cygwin default terminal emulator.
The following terminals are NOT supported or have restricted features:
* Console2
	* Partially; 256 color mode works incorrectly
* cmd.exe
	* Unsupported; though it has ANSI escapes, ncurses recognizes different keys
* Powershell
	* Unsupported; see cmd.exe

Testing limited:
* PuTTY

Links in browser may not open correctly by default. On cygwin, the program 
defaults to using `cygstart`, which uses the Windows default for paths beginning
with "http(s)://". On other platforms, the default is handled by the `webbrowser`
Python module.
If you wish to modify this, you can do one of two things:
* add your preferred browser's directory to the Windows PATH environment variable, or
* specify a BROWSER (cygwin) environment variable (as in `BROWSER=chrome chatango.py`)
The latter implies that there is a link to the executable in `/usr/bin` in cygwin.
This can be created with
`ln -s /cygdrive/c/Program\ Files/.../[browser executable].exe /usr/bin`

To preserve the value of BROWSER, write a line in ~/.bashrc like `export BROWSER=chrome`

There are few good image viewers in windows that support command line arguments,
and fewer if any that attempt to resolve paths with HTTP. By default, the program will
viewer will use the browser through `cygstart`. If you'd prefer to do the same with
videos, change `linkopen.MPV_ARGS` (as shown above) to `[]`.

[This fork](https://gitgud.io/JJXB/chatango-client/tree/master) has more information
