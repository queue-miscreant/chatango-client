Ultra-Meme Chatango CLIent
==========================
Version 6.28
--------------------------

A CLI application written in python with curses input and ANSI escape-colored output.   
Used to implement a client for chatango, an online chatting service.   
Run `python chatango.py` or `./chatango.py` in the directory you extracted it to.  
I recommend making a symlink in /usr/local/bin/ so you don't have to navigate to the folder,
or especially have a million files in ~/

This client is based on chlib.py <https://github.com/cellsheet/chlib>, and uses wcwidth from <https://github.com/jquast/wcwidth>.

My custom script: https://puu.sh/qu6w1/84c4e26f77.py
Requires livestreamer, youtube-dl, and xclip, but if you don't already have
these, seriously consider installing them  

If you want to extend the client somehow, consider looking at the [docs](DOCS.md)

FEATURES:
--------------------------
* Tab completion
* Terminal-resize compatible
* Tracking images and links posted (F2)
* View members of a certain room (F3)
* Alter formatting sent to the chatango (F4)
* Change channel (F5)
	* Supports white, red, and blue channels (and the apparently forgotten "both" channel)
* Colorized output
	* Color text matching a regex or so
* Client commands
	* Type /help while the input box is empty to display a list of commands implemented
* Chat filters based on message attributes

DEPENDENCIES
--------------------------
* Python 3
* Curses (You probably already have this)  
### Technically these are optional since you can change how they open  
* Feh image viewer
* MPV

TODO
-------------------------
### Chatango client-side  
Checking login success better
Better (global) tabbing interface
In-client relogging

CHANGELOG
=========================
## v6.28	*2016/8/11*
* Lods of ebug fixes (Prob'ly)
* Merged client.coloring and client.formatting into client.termform
	* One imported the other anyway
* Hopefully finally got fast scrolling working
* Made colorers *much* more accessible
	* colorByRegex and effectByRegex insert relevant escape sequences at matches
* Added underlining of things in backticks (a la chatango quoting)
* Added coloring of names referenced by @
* Remembered that time overlays were blocking and gave overlays potential for \_resize method
	* All overlays in the stack have this run (defaults to a null lambda with two arguments)
* Relogging and inputting credentials on command line do not save to file
* Changing group with ^t now saves to file
* Moved ~/.creds to ~/.chatango_creds

## v6.2		*2016/8/8*
* Fixed tab-reply to anons and no-accounters
* Added support for logging in without credentials (i.e anons and no-accounters)
* Better link opener interface
* Added -r flag for relogging
* Fixed newlines
	* Apparently at some point, embedding html tags in messages caused chatango's web client to eat them

## v6.1		*2016/8/6*
* Added keys command
* Removed staticize2; staticize is now a function that copies documentation
* Made history its own class
* Fixed tabbing from 'not end of string'
* Added command tabbing
	* As consequence, moved findName into client.display
* Added switching groups (control-t)
* Moved scrollablecontrol to method of overlayBase
* Version numbers will now approach tau for no reason whatsoever

## v6.0		*2016/8/5*
* Reorganized client.py into its own package (i.e, client/)
	* Improves readability, but cross imports seem... strange.
* Instead of mainOverlay.display calculating from selector position, three variables are used to track selection
	* Less same time-complexity, half the iterations
* Moved link opening under client/, and builtins in chatango.py to the new file
* I honestly don't know if this should constitute its own version number, but okay

## v5.3		*2016/7/30*
* Fixed scrollable's "reverse fitwordtolength"
	* This didn't work because it's hard to find a backwards CSI
* Resize to too small no longer breaks the program.
	* All display is blocked until a resize event sets the display to within boundaries again
* Pre-compiled some regexes in chatango.py
* Added function to add 'default' scrollable controls.
	* Things like left moves the cursor back, backspace backspaces
* Pressing \\ now brings up an invisible overlay.
	* \\->n inserts a newline, \\->\\ a \\
* Overlays and colorers now alter by reference, and do not expect a return value
 
## v5.2		*2016/7/27*
* commandOverlray replaces last line instead of "drawing over" it
* Alt-backspace should work in a way that's more sane
* If a command returns an overlay, then the commandOverlay will be replaced by that overlay
	* This is better because it means the overlay stack can be privatized (in main class)
* Revamped entire input delegation system
	* Front-end is the same
	* Back-end no longer uses setattr and getattr
	* This makes string manipulations into integer manipulations
* Made several member variables into private members

## v5.1		*2016/7/16*
* Added asking if opening more than two links at once
* Lacking programs to run this prints blurbs instead of raising exceptions
* Blurbs protected against overflowing
* Fixed listOverlay drawing. Left justify done by client.py, not chatango.py

## v5		*2016/7/16*
* Added scrolling upwards. Either press alt-up or alt-k to go up, and alt-down or alt-j to go down
* Added k and j for up and down in listOverlay
	* Yes, these are born solely from the fact that I use vim
* Upon selecting a message, enter will open all links, and tab will format the message for quoting
* Added wcwidth character width
	* This allows correct width on CJK characters that take two columns to draw
* Redefined link_openers with multiple function arguments, because that's what I was doing before
* Moved onenter to chatango.py so that a "send" function does not have to be passed to client.py
* Reformatted README.md :\^)

## v4.1		*2016/5/16*
* Added "modes" for listinput. Allows different functions to handle data depending on current
* Changed F2 menu to pull number from string. This confirms the wanted link is selected
* Altered the way the client starts up. client.start expects the object that retreives messages to start,
* 	That object's main method
* link_openers have two types now:
	* 	ext|(extension name):	Open extension with 'extension name'
	* 	site|(pattern):		Open link with pattern 'pattern'
	* 	default:		Default

* New input window. Due to the new start feature, it is now possible to start the client before the chat bot.
* Exceptions in the chat bot thread (ie, the functionality supplied to client) should now halt the client

## v4.0 (the important update)	*2016/5/10*
* Completely new display and input methods
* No longer relies on curses drawing; everything is done with variations of print()
* F4 format selector works now

## v3.3		*2016/3/7*
* Removed messageSplit, now pushing a message and drawing lines are in the same process.
	* This eliminates machine coloring errors (such as those when a link would be white as well as text following it)
* Fixed chatango thumbnails showing up in chat.
* Reversed truth values for filters

## v3.2		*2016/2/29*
* Implemented scrolling a la a text editor
* Removed replacing links with "\<LINK #\>"
* Fixed mouse again

## v3.1.2	*2016/2/21*
* Finally fixed garbage control character injection. xterm seems to not flicker anymore.
* Moved link functions to be dependent on chatango.py
	* Greater API freedom; less code to change on Windows.

## v3.1.1	*2016/2/20*
* Added drawing currently unfiltered channels
* Made color input window slightly more resize-friendly (read: made things more full out)
* Daemonized threads should stop together
* Made better API for listinterface keys. Now uses a dictionary of the same type as client.onkey wrappers. For example, 
	* `{'enter':func1,curses.KEY_UP:func2}`

## v3.1	*2016/2/20*
* Changed colorer arguments. Made client more generalized so that argument list is pulled from the bot.
* Modified the name colorer to use intene colors on certain names. Should be easier to tell names apart
* Added chat filtering (space in F5 menu)
	* Drawing filtered channels in the menu pending

## v3.0.1	*2016/2/17*
* Merged bot.py into chatango.py
* Fixed the colors drawing bug.
	* Was caused by drawing too many lines at once, scrolling too much, and drawing past the display height

## v3.0	*2016/2/17*
* Added channel support
	* 	Packets sent to chatango were XOR encrypted, so this was a little difficult
* Added channel selector (F5)
	* 	Filters are still unimplemented
* Doing that "import bot and get credentials" was a bad idea
* Removed aux.py file; reformatted 
* Added new coloring feature. Messages are now drawn in parts corresponding to color.
	* See ""API""
* Due to complication of implementation (and rushing this release), mouse no longer works
* __KNOWN ERRORS__
* Random segfaults on startup. Running a second time seems to resolve it
* For certain terminal widths, coloring algorithm makes colors fail.
	* Widths greater than 40 seem to be okay.

## v2.Something *2016/1/26*
* Refined chat window drawing
	* Scrolls when new lines are needed instead of doing total redraws
* Moved some variables around
	* This includes running credentials pulling on import of the bot 
* Added mouse click support on links

## v2.1 *2015/11/15*
* Added formatting selector (F4)
	* No way to display the color aside from using a GTK window, which I refuse to do
* Fixed long-string drawing on text input
	* Previously, too-long strings would cause a curses error
* Changed credentials file to JSON format
	* It's easy to read from

## v2.0 *2015/11/14*
* Updated chlib.py from git <https://github.com/cellsheet/chlib>
* Updated various input-pulling methods
	* They now pull from the curses screen, and are descended from a single class
* Fixed various drawing methods
* Unicode display/input support
	* Previously multi-byte characters would cause addstr to fail

## v1.4.2 *2015/11/12*
* Added numbers to links display
* Fixed link numbering with multiple links
* Added support for external drawing in display boxes
* Tiny fixes

## v1.4.1 *2015/11/12*
* Created seperate class for displaying boxes (e.g. the ones for user display/link display)
	* Massive restructuring

## v1.4 *2015/11/12*
* Added user display list (F3)
* Reorganized program: extended chat bot now in its own file
	* 	New container that handles relations between the class instead of tightly coupling them
* Fixed bug where lines without spaces would cause an infinite loop
* Fixed regexes to end links at newline or space
* Reformatted color hash to give "friends" the color they wanted

## v1.3.3 *2015/11/12, earliest known version date*
* Directed garbage characters left behind by keys like Super + (Another Key) and Insert away from input
* Slightly modified line-splitter to split at the space only if words are split on the line
* Reorganized methods in the mainWindow class

## v1.3.2
* Added better long-message indenting
* Changed the decode/encode function to stop encoding ' ' as nbsps
	* This was a stupid idea because chatango's HTML client looks for spaces around a name, not non-breaking spaces.
* Added better link comprehension

## v1.3.1
* Moved picture window button to F2
* Fixed picture window drawing
* Added encode/decode HTML escape characters (eg non-breaking space to a space)
* 	Decoded on message download, encoded on mesage upload

## v1.3
* Added picture/link support (F1)
* Added better handling of escape sequences
	* As consequence, added escape to quit
* Removed ability to input control characters, as well as rendering of control characters.
	* They're non-printing for a reason, lads.

## v1.2
* Added a status window (shows username, current number of people in room)
* Fixed drawing on cursor
* Fixed drawing on multi-line indents
	* Previously, indented newlines would drop the last four characters because of the indent.

## v1.1
* Who knows? Colors maybe?
