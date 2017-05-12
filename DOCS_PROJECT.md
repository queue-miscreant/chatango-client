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
