Ultra-Meme Chatango CLIent
==========================
Version 5.3
==========================

A client written in python with curses for chatango, an online chatting service.
Run `python chatango.py` or `./chatango.py` in the directory you extracted it to.
If you really want to, create a link to /usr/local/bin/ so you don't have to navigate to the folder.  

This client is based on chlib.py <https://github.com/cellsheet/chlib>, and uses wcwidth from <https://github.com/jquast/wcwidth>.

My custom script: http://puu.sh/oTJR8/ca83bf5e85.py
Requires livestreamer and youtube-dl

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
* Chat filters based on message attributes

DEPENDENCIES
--------------------------
* Python 3
* Curses (You probably already have this)
### Technically these are optional since you can change how they open
* Feh image viewer
* MPV

API
=====
It's nowhere near comprehensive enough to be called an API,
but this section might help demonstrate the abilities of the client.

DECORATORS
----------
###	client.colorer
>## 	Adds a colorer to be applied to the client.
>## 	Decoratee arguments:
>			msg:		The message as a coloring object. See coloring under objects.
>			*args:		The rest of the arguments. Currently:
>					0:		reply (boolean)
>					1:		history (boolean)
>					2:		channel number

###	client.chatfilter
>## 	Function run on attempt to push message. If any filter returns true, the message is not displayed
>## 	Decoratee arguments:
>			*args:	Same arguments as in client.colorer
		
###	client.onkey(valid_keyname)
>## 	Causes a function to be run on keypress.
>## 	Arguments:
>			valid_keyname:	Self-explanatory. Must be the name of a valid key in curses._VALID_KEYNAMES
>## 	Decoratee arguments:
>			self:	the current client object
	
###	client.command(command_name)
>## 	Declare command. Access commands with \`
>## 	Arguments:
>			command_name:	The name of the command. Type `command_name to run
>## 	Decoratee arguments:
>			self:		The current client object
>			arglist:	Space-delimited values following the command name


###	client.opener(type,pattern_or_extension)
>## 	Function run on attempt to open link. 
>## 	Arguments:
>			type:			0,1, or 2. 0 is the default opener, 1 is for extensions, and 2 is for URL patterns
>			pattern_or_extension:	The pattern or extension. Optional for default opener
>## 	Decoratee arguments:
>			self:	The client object. Passed so that blurbs can be printed from within functions
>			link:	The link being opened
>			ext:	The extension captured. Optional for default opener

###	*See how these are called in chatango.py, such as in F3()*

AUXILIARY CLASSES
-----------------
###	client.coloring(str,default = None)
>## 	A container that holds a string to be colored.
>## 	Arguments/Members:
>		_str:		String being colored
>		default:	Default color to be applied
>## 	Methods:
>		__repr__:	Return _str
>		__add__(oth):	Add oth to _str, returning the instance
		__radd__(oth):	Add str to _oth, returning the instance
>		prepend(new):	Prepend new to the message
>		append(new):	Append new to the message
>		insertColor(position, color = default, add = True):	Insert color pair "color" at position "position". "add" signifies whether to use the predefined colors (default don't)

###	client.scrollable(width)
>##	A container that performs some common textbox operations. Allows string display of width.
>	Arguments:
>		width:		The maximum width allowed to display.
>	Members:
>		_str:		The string contained
>		_pos:		Current cursor position
>		_disp:		Current display position. _disp marks the beginning of the slice, the end is _disp+width
>		width:		The maximum width allowed to display.
>		history:	A list of previous entries of the instance
>		_selhis:	Iterator of history
>	Methods:
>		__repr__:	Returns _str
>		display():	Returns a slice of _text
>		append(new):	Insert new into _str at the current cursor position.
>		backspace():	Delete the character behind the cursor.
>		delchar():	Delete the character at the cursor.
>		delword():	Delete the last word behind the cursor.
>		clear():	Clears the text
>		home():		Moves cursor and display slice back to the beginning
>		end():		Moves cursor and display slice to the end
>		nexthist():	Sets _str to the next (less recent) entry in history
>		prevhist():	Sets _str to the previous (more recent) entry in history,
>				or the empty string if there are no more messages in history
>		appendhist(new):	Appends new to history and keeps history within 50 entries

###	client.botclass():
>##	A bot class. All bot instances (in start) are expected to descend from it
>	Members:
>			parent: 	The current instance of client.main
>	Methods:
>			setparent(overlay):	Sets parent to overlay. Raises exception if overlay is not a client.main

OVERLAYS
--------
###	client.overlayBase()
>##	Base class of overlays. For something to be added to the overlay stack, it must derive from this class.
	All subsequent overlays are descendents of it
>	Members:
>		_altkeys: 	Dictionary of escaped keys, i.e. sequences that start with ESC (ASCII 27)
>				Keys must be ints, values must be functions that take no arguments
>				Special key None is for the Escape key
>		_keys:		ASCII (and curses values) of keys. Keys must be ints,
>				values must be functions that take a single list argument 	
>	Methods:
>		__call__(chars):	Attempt to redirect input based on the _keys dict
>		_callalt(chars):	Alt key backend that redirects ASCII 27 to entries in altkeys
>		display(lines):		Does nothing. This has the effect of not modifying output at all
>		post():			A method that is run after every keypress if the _keys entry
>					Evaluates to something false. e.g. 0, None. Does nothing by default
>		addKeys(newkeys):	Where newkeys is a dictionary, accepts valid keynames (i.e., in
>					client._VALID_KEYNAMES) and updates _keys accordingly
>					Newkeys values are functions with exactly one argument: the overlay.
>		addResize():		Run when an overlay is added. Maps curses.KEY_RESIZE to
					client.main.resize, ensuring that resizing always has the same effect

###	client.listOverlay(outputList,[drawOther,[modes = [""]]])
>##	Displays a list (or string iterable) of objects. Selection controlled with arrow keys (or jk)
>	Arguments:
>		outputList:	The list to output. Simple.
>		drawOther:	A function that takes two arguments: a client.coloring object of a string in
>				outputList, and its position in the list
>		modes:		List of 'modes.' The values are drawn in the lower left corner
>	Members:
>		it:		The "iterator." An integer that points to an index in outList
>		mode:		Similar to it, but for iterating over modes. This is decided at instantiation,
>				so it is the programmer's duty to make a 'mode' functional.
>		list:		The outputList specified during instantiation
>		_modes:		Names of modes. Since these are just for output, they are a private member.
>		_numentries:	Equivalent to len(list), but stored int he class
>		_nummodes:	Equivalent to len(_modes), but stored in the class.
>		_drawOther:	The drawOther specified during instantiation
>	
>	Methods:
>		increment(amt):	Increment it and mod by _numentries
>		chmode(amt):	Increment mode and mod by _nummodes
>		display(lines):	Display a box containing the list entries, with the selected one in reverse video.

###	client.colorOverlay([initColor = [127,127,127]])
>##	Displays 3 bars correlating to a three byte hex color.
>	Arguments:
>		initColor:	The color contained will be initialized to this
>	Members:
>		color:		A list of integers from 0 to 255, containing the value of the color
>		_rgb:		Which color, red, green, or blue, is selected
>	Methods:
>		increment(amt):	Increment color[_rgb] by amt, within the range 0 to 255
>		chmode(amt):	Increment _rgb and mod by 3. Alternatively stated, rotate between colors
>		display(lines):	Display a box containing the list entries, with the selected one in reverse video.
		
###	client.inputOverlay(prompt,[password = False,end = False]):
>##	Displays 3 rows, with input in the middle
>	Arguments:
>		prompt:		A string to display next to input. Similar to the default python function input.
>		password:	Whether to replace the characters in the string with *s, as in a password screen.
>		end:		Whether to end the program on abrupt exit, such as KeyboardInterrupt or pressing ESC
>	Members:
>		text:		A scrollable object containing input
>		_done:		Whether the inputOverlay is finished running or not. waitForInput halts when true.
>		_prompt:	The prompt to display. See above.
>		_password:	Password display. See above.
>		_end:		End on abrupt quit. See above.
>	Methods:
>		_input(chars):
>		_finish():	Finish input. Sets _done to True and closes the overlay.
>		_stop():	Finish input, but clear and cloas the overlay.
>		display(lines):	Display 3 rows in the middle of the screen in the format prompt: input
>		waitForInput():	When an instance of inputOverlay is created in another thread, this allows
>					input to be polled.

###	client.commandOverlay(parent)
>##	Descendant of inputOverlay. However, instead displays client.CHAR_COMMAND followed by input
>	Arguments:
>		parent:		The instance of client.main. Passed so that commands can call display methods.
>	Members:
>		parent:		Instance of client.main. See above.
>	Methods:
>		_run:			Run the command in text. If a command returns an overlay, the commandOverlay
>					will replace itself with the new one.
>		_backspacewrap():	Wraps backspace so that if text is empty, the overlay quits.
>		display(lines):		Display command input on the last available.

###	client.escapeOverlay(scrollable)
>##	Invisible overlay. Analogous to a 'mode' that allows input of escaped characters like newline.
>	Arguments:
>		scrollable:	A scrollable instance to append to.

###	client.escapeOverlay(function)
>##	Invisible overlay. Analogous to a 'mode' that allows confirmation before running a function
>	Arguments:
>		function:	Function with no arguments. Run on press of 'y'.

###	client.mainOverlay(parent)
>##	The main overlay. If it is ever removed, the program quits.
>	Arguments:
>		parent:		The instance of client.main.
>	Members:
>		addoninit:	Exists before __init__. A list of keys to add to the class during __init__.
>				Handled by client.onkey wrapper.
>		text:		A scrollable that contains input.
>		parent:		The instance of client.main.
>		_allMessages:	All messages appended by append
>		_lines:		_allMessages, broken apart by breaklines.
>		_selector:	Select message. Specifically, the number of unfiltered messages 'up'
>		_filtered:	Number of messages filtered. Used to bound _selector.
>	Methods:
>		_post():	See overlayBase.post. This post stops selecting and re-fires display
>		_replaceback():	Opens an escapeOverlay instance.
>		_input(chars):	Append chars as (decoded) bytes to text
>		selectup():	Selects the next message.	
>		selectdown():	Selects the previous message.
>		linklist():	Opens a listOverlay of lastlinks, backwards.
>		isselecting():	Returns _selector. Intened to be used to branch if selecting (i.e if self.isselecting():...)
>		addOverlay(new):Equivalent to self.parent.addOverlay
>		getselect(num):	Gets the selected message. A frontend for _allMessages[_selector] that returns the right message
>		redolines():	Redo enough lines to not be apparent.
>		clearlines():	Clear _lines, _allMessages, _selector, and _filtered
>		append(newline, args = None):	Append [newline,args,len(breaklines(newline))] to _allMessages. If filtered,
>						nothing else happens. If not, breaklines gets appended to _lines.
>		display(lines):	Don't make me explain this. If selecting, it does a dance. If not, it goes up
>				len(lines) in _lines and displays that back, with a bar at the end

CHANGELOG
--------------------------
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

## v4.0		*2016/5/10*
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
	* 	Was caused by drawing too many lines at once, scrolling too much,
	* 		and drawing past the display height

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
	* 	Widths greater than 40 seem to be okay.

## v2.Something *2016/1/26*
* Refined chat window drawing
	* 	Scrolls when new lines are needed instead of doing total redraws
* Moved some variables around
	* 	This includes running credentials pulling on import of the bot 
* Added mouse click support on links

## v2.1 *2015/11/15*
* Added formatting selector (F4)
	* 	No way to display the color aside from using a GTK window, which I refuse to do
* Fixed long-string drawing on text input
	* 	Previously, too-long strings would cause a curses error
* Changed credentials file to JSON format
	* 	It's easy to read from

## v2.0 *2015/11/14*
* Updated chlib.py from git <https://github.com/cellsheet/chlib>
* Updated various input-pulling methods
	* 	They now pull from the curses screen, and are descended from a single class
* Fixed various drawing methods
* Unicode display/input support
	* 	previously multi-byte characters would cause addstr to fail

## v1.4.2 *2015/11/12*
* Added numbers to links display
* Fixed link numbering with multiple links
* Added support for external drawing in display boxes
* Tiny fixes

## v1.4.1 *2015/11/12*
* Created seperate class for displaying boxes (e.g. the ones for user display/link display)
	* 	Massive restructuring

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
	* 	This was a stupid idea because chatango's HTML client looks for spaces around a name, not non-breaking spaces.
* Added better link comprehension

## v1.3.1
* Moved picture window button to F2
* Fixed picture window drawing
* Added encode/decode HTML escape characters (eg non-breaking space to a space)
* 	Decoded on message download, encoded on mesage upload

## v1.3
* Added picture/link support (F1)
* Added better handling of escape sequences
* 	As consequence, added escape to quit
* Removed ability to input control characters, as well as rendering of control characters.
* 	They're non-printing for a reason, lads.

## v1.2
* Added a status window (shows username, current number of people in room)
* Fixed drawing on cursor
* Fixed drawing on multi-line indents
	* Previously, indented newlines would drop the last four characters because of the indent.

## v1.1
* Who knows? Colors maybe?
