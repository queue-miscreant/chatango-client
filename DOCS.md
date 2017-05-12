Project Documentation
=====================
client/ is a package meant to make IRC-like terminal display easier.
Use the line `import client` to get started.

client itself is split up into multple modules:
1. wcwidth.py
	* This module implements the C function wcwidth. This will not be covered in this documentation, please check [the original source code](https://github.com/jquast/wcwidth).
2. display.py
	* This module implements classes used by overlay.py to render text on screen.
3. overlay.py
	* This module implements a system of overlays for text display to the screen. 
4. linkopen.py
	* This module implements the ability to open links with system file viewers based on the extension of the link (e.g, viewnior image viewer for \*.png files)

display.py
====================

The module display.py is intended to do useful things like color text, underline text, or break strings into a number of lines that are smaller than a certain column width.
It is intended for use with a terminal emulator like tmux because it uses ANSI escape sequences.
You can check the [wikipedia article] (https://en.wikipedia.org/wiki/ANSI_escape_code) for more information on these.

To handle this, the module uses a list of valid color names:
* "black"
* "red"
* "green"
* "yellow"
* "blue"
* "magenta"
* "cyan"
* "white"
* ""
* "none"
These are in ascending order by color number (i.e, black is at index 0, and corresponds to '30').

A textcolor is a combination of background and foreground colors. These are stored in a simple list so they can be easily referenced as numbers.
Textcolors can be found in the `_COLORS` list, which defines the following pairs:
* Normal text on normal background
	* Just the "none" background and foreground
* Red text on white background
* Red text and background
* Green text and background
* Blue text and background

These are mainly for interal use by overlay.py, but can be accessed by the function `rawNum()` (see its entry in "Functions")

The module also supports font effects like reverse video. Predefined effects are:
* Reverse video (i.e. if your terminal is in white text on black, it will render as black text on white)
* Underline

See `defEffect()` to define these.

Exceptions
----------
This module defines a single exception, `DisplayException`. Use this to catch potential errors in functions like getColor.

Functions
-------------------
Here is a list of functions defined by the module.

###defColor(foreground,background="none",intense=False)
Define a color. `foreground` and `background` should be valid color names as defined above.
`intense` sets whether to use intense colors for the text. On some terminal emulators, this also has the effect of bolding text.
`foreground` can also be an integer from 0 to 256, for 256-color terminal support.
Returns the color's index in `_COLORS` (without predefined colors).

###def256colors()
Define all 256 colors. Returns the index of the start of the 256 colors in `_COLORS` (without predefined colors)

###defEffect(on,off)
Define an effect. on is the string used to turn the effect on, and off is used to turn it off.
This is intended for 'invisible' strings like ANSI escapes, but not strictly enforced. Text in Coloring objects may render improperly.

###getColor(colornumber)
Get the color `colornumber` in `_COLORS`. This will ignore predefined colors. Raises DisplayException if no such color exists.

###rawNum(colornumber)
Get the predefined color `colornumber`. This is intended to be used as `getColor(rawNum(colornumber))`

###collen(string)
Get the column width of the string. This is equivalent to `wcswidth` in `wcwidth.py`, but ignores ANSI escape sequences.
For example, `collen("\x1b[mあ")` will return 2, since the character 'あ' occupies 2 columns.

Classes
-------------------
Here is a list of classes defined by this module.

###Coloring(string)
An object containing a string and applied colors and effects. The `string` argument specifies the string to use for coloring.
Once a Coloring object is defined, more colors and effects CANNOT be defined.

####Methods:

```
Coloring.coloredAt(postition)
```
Returns whether the instance has a color/effect at string index `position`
```Coloring.insertColor(position,color)```
Inserts a color number `color` at position `position`
```Coloring.effectRange(start,end,effect)```
Adds an effect with number `effect` from string slice `[start:end]`.
effectRange(0,-1,0) will make the entire string until the last character reverse video.
```
Coloring.addGlobalEffect(effect)
```
Turn an effect on the entire string. Shorthand for `effectRange(0,len(str),effect)` where `str` is the string contained.
```
Coloring.colorByRegex(regex, color, fallback = None, group = 0)
```
Insert a color from a compiled regex `regex`.
When the regex is matched, `color` will be applied to the match (with regex group `group`).
This function preserves the color immediately before the match.
e.g.: If a completely green string "(Green)" has blue inserted somewhere in it, the string will have colors "(Green)(Blue)(Green)"
`color` should be an integer or function that returns an integer.
`fallback` is the fallback color if no colors exist before the match. Defaults to 0: normal text on normal background
```
Coloring.effectByRegex(regex, effect, group = 0)
```
Adds an effect with effect number `effect` to the regex match.
`group` selects the regex group.

```
Coloring.breaklines(self,length,outdent="")
```
Applies coloring and effects to the contained string and breaks it into lines with column width no greater than `length`
`outdent` signifies a leading string for all lines besides the first

####Magic Methods:

`repr(Coloring)`:	Returns the formatted contents of the object: its string, coloring/effects, and positions for these coloring/effects.
`str(Coloring)`:	Returns the object's contained string.
`format(Coloring)`:	Returns the string with all colors and effects applied to it. Note that if you want to restrict column width, use `breaklines`


###	client.scrollable(width)
a container that performs some common textbox operations. allows string display of width.
arguments:
```
	width:		the maximum width allowed to display.
```
members:
```
	_str:		The string contained
	_pos:		Current cursor position
	_disp:		Current display position. _disp marks the beginning of the slice, the end is _disp+width
	width:		The maximum width allowed to display.
	history:	A list of previous entries of the instance
	_selhis:	currently selected entry of history
```
Methods:
```
	__repr__:	Returns _str
	display():	Returns a slice of _text
	append(new):	Insert new into _str at the current cursor position.
	backspace():	Delete the character behind the cursor.
	delchar():	Delete the character at the cursor.
	delword():	Delete the last word behind the cursor.
	clear():	Clears the text
	home():		Moves cursor and display slice back to the beginning
	end():		Moves cursor and display slice to the end
	nexthist():	Sets _str to the next (less recent) entry in history
	prevhist():	Sets _str to the previous (more recent) entry in history,
			or the empty string if there are no more messages in history
	appendhist(new):	Appends new to history and keeps history within 50 entries
```





DECORATORS
----------
###	client.colorer
Adds a colorer to be applied to the client.  
Decoratee arguments:  
```
	msg:		The message as a coloring object. See coloring under objects.
	*args:		The rest of the arguments. Currently:
			0:		reply (boolean)
			1:		history (boolean)
			2:		channel number
```

###	client.chatfilter
Function run on attempt to push message. If any filter returns true, the message is not displayed  
Decoratee arguments:
```
	*args:	Same arguments as in client.colorer
```

###	client.onkey(valid_keyname)
Causes a function to be run on keypress.  
Arguments:
```
	valid_keyname:	Self-explanatory. Must be the name of a valid key in curses._VALID_KEYNAMES
```
Decoratee arguments:
```
	self:	the current client object
```

###	client.command(command_name)
Declare command. Access commands with /  
Arguments:
```
	command_name:	The name of the command. Type /command_name to run
```
Decoratee arguments:
```
	self:		The current client object
	arglist:	Space-delimited values following the command name
```

###	client.opener(type,pattern_or_extension)
Function run on attempt to open link.  
Arguments:
```
	type:			0,1, or 2. 0 is the default opener, 1 is for extensions, and 2 is for URL patterns
	pattern_or_extension:	The pattern or extension. Optional for default opener
```
Decoratee arguments:
```
	self:	The client object. Passed so that blurbs can be printed from within functions
	link:	The link being opened
	ext:	The extension captured. Optional for default opener
```

###	*See how these are called in chatango.py, such as in F3()*

AUXILIARY CLASSES
-----------------
###	client.botclass():
A bot class. All bot instances (in start) are expected to descend from it
Members:
```
	parent:		The current instance of client.main
```
Methods:
```
	setparent(overlay):	Sets parent to overlay. Raises exception if overlay is not a client.main
```

OVERLAYS
--------
###	client.overlayBase()
Base class of overlays. For something to be added to the overlay stack, it must derive from this class. 
All subsequent overlays are descendents of it  
Members:
```
	_altkeys:	Dictionary of escaped keys, i.e. sequences that start with ESC (ASCII 27)
			Keys must be ints, values must be functions that take no arguments
			Special key None is for the Escape key
	_keys:		ASCII (and curses values) of keys. Keys must be ints,
			values must be functions that take a single list argument	
```
Methods:
```
	__call__(chars):	Attempt to redirect input based on the _keys dict
	_callalt(chars):	Alt key backend that redirects ASCII 27 to entries in altkeys
	display(lines):		Does nothing. This has the effect of not modifying output at all
	post():			A method that is run after every keypress if the _keys entry
				Evaluates to something false. e.g. 0, None. Does nothing by default
	addKeys(newkeys):	Where newkeys is a dictionary, accepts valid keynames (i.e., in
				client._VALID_KEYNAMES) and updates _keys accordingly
				Newkeys values are functions with exactly one argument: the overlay.
	addResize():		Run when an overlay is added. Maps curses.KEY_RESIZE to
				client.main.resize, ensuring that resizing always has the same effect
```

###	client.listOverlay(outputList,[drawOther,[modes = [""]]])
Displays a list (or string iterable) of objects. Selection controlled with arrow keys (or jk)  
Arguments:
```
	outputList:	The list to output. Simple.
	drawOther:	A function that takes two arguments: a client.coloring object of a string in
			outputList, and its position in the list
	modes:		List of 'modes.' The values are drawn in the lower left corner
```
Members:
```
	it:		The "iterator." An integer that points to an index in outList
	mode:		Similar to it, but for iterating over modes. This is decided at instantiation,
			so it is the programmer's duty to make a 'mode' functional.
	list:		The outputList specified during instantiation
	_modes:		Names of modes. Since these are just for output, they are a private member.
	_numentries:	Equivalent to len(list), but stored int he class
	_nummodes:	Equivalent to len(_modes), but stored in the class.
	_drawOther:	The drawOther specified during instantiation
```
Methods:
```
	increment(amt):	Increment it and mod by _numentries
	chmode(amt):	Increment mode and mod by _nummodes
	display(lines):	Display a box containing the list entries, with the selected one in reverse video.
```

###	client.colorOverlay([initColor = [127,127,127]])
Displays 3 bars correlating to a three byte hex color.
Arguments:
```
	initColor:	The color contained will be initialized to this
```
Members:
```
	color:		A list of integers from 0 to 255, containing the value of the color
	_rgb:		Which color, red, green, or blue, is selected
```
Methods:
```
	increment(amt):	Increment color[_rgb] by amt, within the range 0 to 255
	chmode(amt):	Increment _rgb and mod by 3. Alternatively stated, rotate between colors
	display(lines):	Display a box containing the list entries, with the selected one in reverse video.
```
		
###	client.inputOverlay(prompt,[password = False,end = False]):
Displays 3 rows, with input in the middle
Arguments:
```
	prompt:		A string to display next to input. Similar to the default python function input.
	password:	Whether to replace the characters in the string with *s, as in a password screen.
	end:		Whether to end the program on abrupt exit, such as KeyboardInterrupt or pressing ESC
```
Members:
```
	text:		A scrollable object containing input
	_done:		Whether the inputOverlay is finished running or not. waitForInput halts when true.
	_prompt:	The prompt to display. See above.
	_password:	Password display. See above.
	_end:		End on abrupt quit. See above.
```
Methods:
```
	_input(chars):
	_finish():	Finish input. Sets _done to True and closes the overlay.
	_stop():	Finish input, but clear and cloas the overlay.
	display(lines):	Display 3 rows in the middle of the screen in the format prompt: input
	waitForInput():	When an instance of inputOverlay is created in another thread, this allows
			input to be polled.
```

###	client.commandOverlay(parent)
Descendant of inputOverlay. However, instead displays client.CHAR_COMMAND followed by input
Arguments:
```
	parent:		The instance of client.main. Passed so that commands can call display methods.
```
Members:
```
	parent:		Instance of client.main. See above.
```
Methods:
```
	_run:			Run the command in text. If a command returns an overlay, the commandOverlay
				will replace itself with the new one.
	_backspacewrap():	Wraps backspace so that if text is empty, the overlay quits.
	display(lines):		Display command input on the last available.
```

###	client.escapeOverlay(scrollable)
Invisible overlay. Analogous to a 'mode' that allows input of escaped characters like newline.
Arguments:
```
	scrollable:	A scrollable instance to append to.
```

###	client.escapeOverlay(function)
Invisible overlay. Analogous to a 'mode' that allows confirmation before running a function
Arguments:
```
	function:	Function with no arguments. Run on press of 'y'.
```

###	client.mainOverlay(parent)
The main overlay. If it is ever removed, the program quits.
Arguments:
```
	parent:		The instance of client.main.
```
Members:
```
	addoninit:	Exists before __init__. A list of keys to add to the class during __init__.
			Handled by client.onkey wrapper.
	text:		A scrollable that contains input.
	parent:		The instance of client.main.
	_allMessages:	All messages appended by append
	_lines:		_allMessages, broken apart by breaklines.
	_selector:	Select message. Specifically, the number of unfiltered messages 'up'
	_filtered:	Number of messages filtered. Used to bound _selector.
```
Methods:
```
	_post():		See overlayBase.post. This post stops selecting and re-fires display
	_replaceback():		Opens an escapeOverlay instance.
	_input(chars):		Append chars as (decoded) bytes to text
	selectup():		Selects the next message.	
	selectdown():		Selects the previous message.
	linklist():		Opens a listOverlay of lastlinks, backwards.
	isselecting():		Returns _selector. Intened to be used to branch if selecting (i.e if self.isselecting():...)
	addOverlay(new):	Equivalent to self.parent.addOverlay
	getselect(num):		Gets the selected message. A frontend for _allMessages[_selector] that returns the right message
	redolines():		Redo enough lines to not be apparent.
	clearlines():		Clear _lines, _allMessages, _selector, and _filtered
	append(newline, args = None):	Append [newline,args,len(breaklines(newline))] to _allMessages. If filtered,
					nothing else happens. If not, breaklines gets appended to _lines.
	display(lines):		Don't make me explain this. If selecting, it does a dance. If not, it goes up
				len(lines) in _lines and displays that back, with a bar at the end
```
