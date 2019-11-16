Changelog
=========================
## v6.28318530717 *2019/11/16*
When splitting the README from the changelog, I forgot to add the file to the repo.
Due to an unfortunate incident involving git removing all files that weren't in
the repo, the changelog was briefly lost. All updates since the last are 
gathered in this version.
* Input-based overlays now have awaitable futures, callbacks, etc. consistently
* Key handling has been placed in its own container class, `KeyContainer`
	* Contains all globals in `base` that were involved in keys, including mouse and lookup tables
	* Supports higher-level mouse ungetting
	* If a overlay has no callback for a key, it tries the next highest overlay
		* Attempts to find an overlay with a callback as high as most recent overlay with `OverlayBase.replace`
	* There should be little functional difference between decorated methods, class-decorated functions, and instance-decorated functions
* Methods that are key handlers of a particular class can be decorated with `key_handler`
	* `key_handler` expects one argument: the key, with optional extra keyword arguments to pass into the method
	* Correspondingly, `OverlayBase.key_handler` adds a key to either a particular instance, or all future instances of the class
		* Unfortunately, due to language limitations I don't care to circumvent, the first `add_key` will bind class handlers to the instance
		* Precedence is determined by the MRO
* Moved associated coloring variables in `display` into a single class (with singular standard instance)
	* Color definitions and effect definitions are stored here
	* 256 color support (including grayscale) is stored here instead of in the `Screen`
* Added new class `JustifiedColoring`
	* Handles ListOverlays needing special justification (with an optional right-aligned portion)
	* Trims strings that are too long by inserting ellipsis into the middle
	* Supports indicator lamps (i.e., for displaying colors)
		* InputMux heavily relies on these to display current value
* Blurbs now support coloring using defined color numbers
	* They also use a JustifiedColoring instance instead of special justification
* `ChatOverlay`s now use `Message` class; `Message`s is now a container class thereof
	* `Message` is a subclass of `Coloring`, and defines a consistent way to re-apply effects/colors
	* `ChatOverlay.colorize_message` is now a method of (subclasses of) `Message`
		* Same goes for `filter_message`
	* `Message` classes support running key callbacks when selected in a ChatOverlay 
		* `ChatOverlay` runs `Message` mouse callbacks corresponding to the message clicked by default
	* Caching is done within the instance instead of in `Messages`
		* `Messages` keeps track of redraw count to validate cache
		* `Message` objects keep track of coloring hash and width to validate self
* `linkopen` is more reliable
	* Supports asynchronously getting OpenGraph tags, but not with any sort of hierarchy in mind
	* Exceptions caused by opening links are caught by `open_link`, logged, and a blurb is pushed to alert the user
	* `open_link` works on lists of strings as well as strings
		* A warning message is issued when opening `open_link.warning_count` or more links
	* Supports adding callbacks for when an unvisited link is opened
* Created and fixed strange error where reverse video would be used for non-replies
	* Somehow an (empty) list reference got passed in instead of a boolean
		* When that list reference had an entry added, it went from False to True
	* This is for my personal reference to remember that Python can handle short-circuiting weirdly

## v6.2831853071 *2019/1/8*
* Continued refactoring so hard that I split the project in two
	* Python interface to Chatango can now be found [here](https://gitgud.io/cubebert/pytango)

## v6.283185307 *2018/12/25*
* Refactored a lot of code
	* Using Python naming conventions
	* Split `client/overlay` into `base`, `overlay`, and `chat`
	* Split `overlay.Main` into `base.Blurb`, `base.Screen`, `base.Manager`
		* Use `Screen.blurb.push` instead of `printBlurb`
	* Canonical way to add keys as partialmethods is with `BaseOverlay.key_handler(key_name)`
		* Can also override return value with second parameter
		* Can be stacked over multiple lines
		* By default, `add_keys` lacks binding self, to make `__init__`s easier
	* Names from `linkopen` are not exposed on `import client`
		* Use `from client import linkopen` instead
	* Overlays now have shortcut properties to their parent's height and width
* Made code entry a lot cleaner
	* Generalized and standardized save files with `_Persistent`
	* Updated to use `argparse` instead of horrendous loop over `sys.argv`

## v6.28318530 *2018/2/26*
* Reworked Messages storage object
	* Scrolling is no longer limited to selecting the highest message
	* Drawing is no longer selectively from the top or bottom depending on message height
	* Arbitrary length lines that can be recalculated at whim with redolines
	* Redolines and recolorlines are no longer arbitrarily coroutines
* Added InputMuxer, a class to help build menus that manipulate a list variables in some context
	* Formatting and options now produce overlays through this
* Added MessageScrollOverlay and addMessageScroll, a helper function which builds instances of the former
	* Features message scrolling on keypresses `a-k` and `a-j`, `n` and `N`
	* Jump to message on keypress `enter`
	* Built ctrl-f message searching on top of these functions

## v6.2831853 *2018/1/18*
* Rewrote much of the infrastructure with asyncio
	* Uses callbacks and futures for things like InputOverlays
	* Rewrote ch.py (the chatango library) with async calls
* If a message is very long, then selecting the next message down will display more of it instead
* Added lazy re-colorization, line breaking, and fitering
* Added DisplayOverlay, which displays (lists of) strings or Coloring objects
	* Used in implementation of reply accumulator and ctrl-f
* Added more vim-like features to ListOverlays
	* Added VisualListOverlay, which allows selecting a set of elements from its list at once
	* Added `g` and `G` keybindings that go to the beginning and end of the list
* Segregated non-display functions and classes in client/display into its own file, client/util.py
* Separated out Messages container and MainOverlay
	* Added method to Messages which allows iteration over items for which a lambda returns true
* Made resize and display calls asynchronous
* Moved error message for importing client/overlay into overlay.Main.run, since that more actively requires it
* Better, but imperfect filesystem tabbing that completes file paths
* Bugfix where attempting to bind multiple alt keys would fail binding all but the last
* Bugfix where clicking on whitespace without list entries in ListOverlays would crash them

## v6.283185 *2017/3/25*
* "Better" extensibility
	* Changed import order to allow importing classes like ChatBot
	* Moved credentials into directory ~/.cubecli
	* Moved custom.py into ~/.cubecli
	* All legacy credential files should be handled automatically by the main script
* Tinkered some with how scrollables draw, but it's still buggy
* Added cyclical scrolling
	* That is, tab will generate a list and more tabs (and s-tabs) will cycle
* Bugfix where ESC did nothing

## v6.28318	*2017/1/16*
* Added mouse support again
	* Clicking on links in main interface
	* Automatically supported in ListOverlays
* Added new color picker
* Fixed slight error when newlines would begin with an @(member)
* Moved 256 colors to client/overlay.py so that non-256 mode is supported
* Added options menu
	* Turn on mouse, anon colors, link warning threshold, etc
* Added function to override return value
	* can be used so that post functions in overlays won't fire
* Slightly changed how functions are looked up for special keys
	* Pasting in characters begining with \t or \n should work now

## v6.2831	*2016/10/16*
* Reformatted docstrings
* Objects are now TitleCased
* Removed deprecated Coloring object
* Added daemonize decorator in client.linkopen. Predefined openers have been adjusted accordingly
* Limited scope of imports (from client.display) in client.overlay
* Removed importing each module in the package
* Finshed new coloring object from previous version

## v6.283	*2016/10/8*
* Preference for tabbing based on who talked more recently
* Fixed resize callbacks in overlay objects
* Changed calling an overlay to be the display; consequently runkey defines key behavior
	* Changed command character to \` (haven't I done that before once) because : and / are too troublesome
* Moved some functionality from chatango.py to chlib.py
	* Some groups from regexes were selected wrong
	* Made it more readable, compiled regexes
* New experimental coloring object
	* Experimentally faster and less variant than old version
	* Still needs effect range cascading (WIP)
* New character-by-character breaklines
	* Experimentally faster (and lack of regexes feels less cheaty)
* More commandline specs
	* Argument reading done in one iteration over argv
	* Credential read/write-ability is set by arguments passed in
* Reworked program flow
	* A single function argument (and its arguments afterword) is passed into client.(overlay.)start
	* This becomes its own thread, so be sure to use inputOverlay.waitForInput and not runOnDone
	* DO NOT CONFUSE WITH OVERLAY THREAD; any overlay should use runOnDone

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
	* Same time complexity, half the iterations
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
* Redefined `link_openers` with multiple function arguments, because that's what I was doing before
* Moved onenter to chatango.py so that a "send" function does not have to be passed to client.py
* Reformatted README.md :\^)

## v4.1		*2016/5/16*
* Added "modes" for listinput. Allows different functions to handle data depending on current
* Changed F2 menu to pull number from string. This confirms the wanted link is selected
* Altered the way the client starts up. client.start expects the object that retreives messages to start,
* 	That object's main method
* `link_openers` have two types now:
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
* Modified the name colorer to use intense colors on certain names. Should be easier to tell names apart
* Added chat filtering (space in F5 menu)
	* Drawing filtered channels in the menu pending

## v3.0.1	*2016/2/17*
* Merged bot.py into chatango.py
* Fixed the colors drawing bug.
	* Was caused by drawing too many lines at once, scrolling too much, and drawing past the display height

## v3.0	*2016/2/17*
* Added channel support
	* Packets sent to chatango were XOR encrypted, so this was a little difficult
* Added channel selector (F5)
	* Filters are still unimplemented
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
	* New container that handles relations between the class instead of tightly coupling them
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
