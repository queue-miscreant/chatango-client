###Ultra-Meme Chatango CLIent
###Version 3.0.1	

##A client written in curses for chatango, an online chatting service.
##Run `./chatango.py` in the directory you extracted it to.
##If you really want to, create a link to /usr/local/bin/ so you don't have to navigate to the folder.

##This client is based on chlib.py <https://github.com/cellsheet/chlib.git>

===============================================================

FEATURES:
	Tab completion
	Terminal-resize compatible
	Tracking images and links posted
		Press F2 to open menu (pending mouse support for clicking on <LINK #>)
	View members of a certain room
		Press F3 to open menu
	Alter formatting sent to the server
		F4
	Change channel
		Supports white, red, and blue channels (pending filtering)
	
	Alterable "colorers"
		Color text matching a regex or so

""API""
	It's nowhere near comprehensive enough to be called an API,
	but this section helps demonstrate the abilities of the display.
	__DECORATORS__
	client.colorer
		Adds a colorer to be applied to the client.
		Decorated function arguments:
			base:		The "base message." Look for patterns here
			coldic:		The color dictionary; this must be retained between colorers
			default:	The default color to insert
			*args:		The rest of tha arguments. Currently:
					0:		Channel number
		
		Format for color dictionary is {draw_before_location:color}
		Where draw_before_location is a position in the string the color stops drawing at
			and color is the curses color (e.g., ones that have been pulled with color_pair)
		
	client.onkey(keyname or curses key value)
		Causes a function to be run on keypress.
		Decorated function arguments:
			self:	the current client object
	
	client.command(command name)
		/(command name) will run the function
		Decorated function arguments:
			arglist:	Space-delimited values following the command name
	
	__CLASSES__
	client.listinput(screen,string iterable)
		Class that draws a list that covers the chat.
		
	client.colorinput(screen,string iterable)
		Class that draws a color selector over the chat.
		
	*See how these are called in chatango.py, such as in F3()*

#CHANGELOG

>#v3.0.1	*2016/2/17*
>##	Merged bot.py into chatango.py
>##	Fixed the colors drawing bug.
>		Was caused by drawing too many lines at once, scrolling too much,
>			and drawing past the display height

>#v3.0	*2016/2/17*
>##	Added channel support
>		Packets sent to chatango were XOR encrypted, so this was a little difficult
>##	Added channel selector (F5)
>		Filters are still unimplemented
>##	Doing that "import bot and get credentials" was a bad idea
>##	Removed aux.py file; reformatted 
>##	Added new coloring feature. Messages are now drawn in parts corresponding to color.
>#		See ""API""
>##	Due to complication of implementation (and rushing this release), mouse no longer works
>##	__KNOWN ERRORS__
>##	Random segfaults on startup. Running a second time seems to resolve it
>##	For certain terminal widths, coloring algorithm makes colors fail.
>		Widths greater than 40 seem to be okay.

>#v2.Something *2016/1/26*
>##	Refined chat window drawing
>		Scrolls when new lines are needed instead of doing total redraws
>##	Moved some variables around
>		This includes running credentials pulling on import of the bot 
>##	Added mouse click support on links

>#v2.1 *2015/11/15*
>##	Added formatting selector (F4)
>		No way to display the color aside from using a GTK window, which I refuse to do
>##	Fixed long-string drawing on text input
>		Previously, too-long strings would cause a curses error
>##	Changed credentials file to JSON format
>		It's easy to read from

>#v2.0 *2015/11/14*
>##	Updated chlib.py from git <https://github.com/cellsheet/chlib>
>##	Updated various input-pulling methods
>		They now pull from the curses screen, and are descended from a single class
>##	Fixed various drawing methods
>##	Unicode display/input support
>		previously multi-byte characters would cause addstr to fail

>#v1.4.2 *2015/11/12*
>##	Added numbers to links display
>##	Fixed link numbering with multiple links
>##	Added support for external drawing in display boxes
>##	Tiny fixes

>#v1.4.1 *2015/11/12*
>##	Created seperate class for displaying boxes (e.g. the ones for user display/link display)
>		Massive restructuring

>#v1.4 *2015/11/12*
>##	Added user display list (F3)
>##	Reorganized program: extended chat bot now in its own file
>		New container that handles relations between the class instead of tightly coupling them
>##	Fixed bug where lines without spaces would cause an infinite loop
>##	Fixed regexes to end links at newline or space
>##	Reformatted color hash to give "friends" the color they wanted

>#v1.3.3 *2015/11/12, earliest known version date*
>##	Directed garbage characters left behind by keys like Super + (Another Key) and Insert away from input
>##	Slightly modified line-splitter to split at the space only if words are split on the line
>##	Reorganized methods in the mainWindow class

>#v1.3.2
>##	Added better long-message indenting
>##	Changed the decode/encode function to stop encoding ' ' as '&nbsp;'
>		This solves the tagging and word splits because chatango's HTML client
>		looks for spaces around a name, not non-breaking spaces.
>		
>		By its very nature, non-breaking spaces don't break, so HTML viewers will
>		try not to do a linebreak on that space.
>##	Added better link comprehension

>#v1.3.1
>##	Moved picture window button to F2
>##	Fixed picture window drawing
>##	Added encode/decode HTML escape characters (eg &nbsp; to a space)
>##		Decoded on message download, encoded on mesage upload

>#v1.3
>##	Added picture/link support (F1)
>##	Added better handling of escape sequences
>##		As consequence, added escape to quit
>##	Removed ability to input control characters, as well as rendering of control characters.
>##		They're non-printing for a reason, lads.

>#v1.2
>##	Added a status window (shows username, current number of people in room)
>##	Fixed drawing on cursor
>##	Fixed drawing on multi-line indents
>		Previously, indented newlines would drop the last four characters because of the indent.

>#v1.1
>##	Who knows? Colors maybe?
