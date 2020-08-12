Cuboid Chatango Client
==========================
Version 6.283185307179
--------------------------
A terminal application for chatango, an online chatroom.
There is currently no setup script; just run `python chatango.py`
or `./chatango.py` in the directory you extracted it to.

Features:
--------------------------
* Link accumulation (F2)
* Member list (F3)
* Custom message formatting (F4)
	* Font and font size will not be reflected, but "close" colors will be used in 256 color mode
* Change channel (F5)
	* Supports white, red, and blue channels (and the erroneous "both" channel)
* Client commands
	* Type `/help` while the input box is empty to display a list of commands implemented
* Ctrl-f substring searching and reply accumulation
	* Jumping to found messages
* Anonymous and pseudo-anonymous joins


Dependencies:
--------------------------
* [Terminal Cancer](https://github.com/queue-miscreant/terminal-cancer) and its dependencies
* [Pytango](https://github.com/queue-miscreant/pytango)


Adding custom modules:
--------------------------
On startup, the path `~/.cubecli` is created to contain persistent data (in cleartext)
such as username, room name, and options. The directory `~/.cubecli/custom` is also
added to contain modules. Unless the `-nc` option is specified, all modules in the
folder are imported. This is where the above-mentioned goes.
