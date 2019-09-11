#!/usr/bin/env python3
#base.py
'''
Base classes for overlays and curses screen abstractions.
Screen implements a stack of overlays and sends byte-by-byte curses input to
the topmost one. Output is not done with curses display, but line-by-line
writes to the terminal buffer (`sys.stdout` is reassigned to a temporary file
to keep output clean)
'''
try:
	import curses
except ImportError:
	raise ImportError("Could not import curses; is this running on Windows cmd?")

import sys
import os
import asyncio
import traceback
import inspect
from functools import partial
from signal import SIGTSTP, SIGINT #redirect ctrl-z and ctrl-c

from .display import CLEAR_FORMATTING, collen, ScrollSuggest, Coloring

__all__ = ["quitlambda", "Box", "OverlayBase", "TextOverlay", "Manager"]

_REDIRECTED_OUTPUT = "/tmp/client.log"
#HANDLER-HELPER FUNCTIONS-------------------------------------------------------
def staticize(func, *args, doc=None, **kwargs):
	'''functools.partial, but conserves or adds documentation'''
	ret = partial(func, *args, **kwargs)
	ret.__doc__ = doc or func.__doc__ or "(no documentation)"
	return ret

class override:
	'''
	Create a new function that returns `ret`. Changes the value of a key's
	return value to control redrawing/removing overlays
	'''
	def __init__(self, func, ret=0, nodoc=False):
		self.func = func
		self.ret = ret

		if not nodoc:
			doc_text = func.__doc__
			if doc_text is not None:
				if ret == 0:
					doc_text += " (keeps overlay open)"
				elif ret == -1:
					doc_text += " (and close overlay)"
			self.__doc__ = doc_text	#preserve documentation text

	def __call__(self, *args):
		self.func(*args)
		return self.ret

class KeyMethod:
	'''
	Wrapper for overlay methods.
	When KeyContainer.__call__ is supplied with multiple characters, if a
	handler for the key is found, then the rest of the characters are passed
	into the handler, along with the rest of the arguments to __call__
	'''
	def __init__(self, func):
		self._func = func
		self.__doc__ = func.__doc__
	def __call__(self, keys, *args):
		return self._func(keys, *args)
	def __eq__(self, other):
		return self._func == other

#Key setup
class KeyContainer:
	'''Object for parsing key sequences and passing them onto handlers'''
	_VALID_KEYNAMES = {
		  "tab":		9
		, "enter":		10
		, "backspace":	127
	}
	#these keys point to another key
	_KEY_LUT = {
		  curses.KEY_BACKSPACE:	127		#undo curses ^h redirect
		, curses.KEY_ENTER:		10		#numpad enter
		, 13:					10		#CR to LF, but curses does it already
	}
	MOUSE_MASK = 0
	#PRESSED tends to make curses.getch tends hang on nodelay; wheel is separate
	_MOUSE_BUTTONS = {
		  "left":		curses.BUTTON1_RELEASED
		, "middle":		curses.BUTTON2_RELEASED
		, "right":		curses.BUTTON3_RELEASED
		, "wheel-up":	curses.BUTTON4_PRESSED
		, "wheel-down":	2**21
	}
	_MOUSE_ERROR = "mouse callback argument mismatch: expected signature "\
		"(x, y, {0}) or ({0})"
	_last_mouse = None	#curses.ungetmouse but not broken

	def __init__(self):
		self._keys = {
			27:						KeyMethod(self._callalt)
			, curses.KEY_MOUSE:		KeyMethod(self._callmouse)
		}
		self._altkeys = {}
		self._mouse = {}

	def screen_keys(self, screen):
		self._keys.update({
			12:	screen.redraw_all							#^l
			, curses.KEY_RESIZE:	screen.schedule_resize
		})

	def __call__(self, chars, *args):
		'''
		Run a key's callback. This expects a single argument: a list of numbers
		terminated by -1. Subsequent arguments are passed to the key handler.
		Returns singleton tuple if there is no handler, otherwise propagates 
		handler's return
		'''
		try:
			char = self._KEY_LUT[chars[0]]
		except KeyError:
			char = chars[0]

		#ignore the command character and trailing -1
		#second clause ignores heading newlines
		fun, other_keys = None, None
		if (char in self._keys) and (char == 27 or len(chars) <= 2 or char > 255):
			fun, other_keys = self._keys[char], chars[1:] or [-1]
		elif -1 in self._keys and (char in (9, 10, 13) or char in range(32, 255)):
			fun, other_keys = self._keys[-1], chars[:-1]
		if fun is not None and other_keys is not None:
			if isinstance(fun, KeyMethod):
				return fun(other_keys, *args)
			return fun(*args)
		return tuple()

	def __dir__(self):
		'''Get a list of keynames and their documentation'''
		ret = []
		for i, j in self._VALID_KEYNAMES.items():
			#ignore named characters and escape, they're not verbose
			if i in ("^[", "^i", "^j", chr(127), "mouse"):
				continue
			if i == ' ':
				i = "space"
			doc_string = ""
			format_string = ""
			if j in self._keys:
				doc_string = inspect.getdoc(self._keys[j])
				format_string = "{}: {}"
			elif j in self._altkeys:
				doc_string = inspect.getdoc(self._altkeys[j])
				format_string = "a-{}: {}"
			else:
				continue

			if not doc_string:
				doc_string = "(no documentation)"
			ret.append(format_string.format(i, doc_string))
		return ret

	def _callalt(self, chars, *args):
		'''Run a alt-key's callback'''
		return self._altkeys[chars[0]](*args) \
			if chars[0] in self._altkeys else tuple()

	def _callmouse(self, chars, *args):
		'''Run a mouse's callback. Saves invalid mouse data for next call'''
		chars = [i for i in chars if i != curses.KEY_MOUSE]
		if chars[0] != -1:
			#control not returned to loop until later
			asyncio.get_event_loop().call_soon(self.run_key, chars, *args)
		try:
			if self._last_mouse is not None:
				x, y, state = self._last_mouse	#pylint: disable=unpacking-non-sequence
				KeyContainer._last_mouse = None
			else:
				_, x, y, _, state = curses.getmouse()
			error_sig = "..."
			if state not in self._mouse:
				if -1 not in self._mouse:
					KeyContainer._last_mouse = (x, y, state)
					return tuple()
				error_sig = "(state, ...)"
				args = (state, *args)
				state = -1
			try:
				return self._mouse[state](x, y, *args)
			except TypeError:
				return self._mouse[state](*args)
		except curses.error:
			pass
		except TypeError as exc:
			raise TypeError(self._MOUSE_ERROR.format(error_sig)) from exc

		return tuple()

	def mouse(self, x, y, state, *args):
		'''Unget some mouse data and run the associated mouse callback'''
		KeyContainer._last_mouse = (x, y, state)
		return self._callmouse([-1], *args)

	def add_key(self, key_name, handler, method_self=None):
		'''Key addition that supports some nicer names than ASCII numbers'''
		if not inspect.ismethod(handler) and method_self is not None:
			handler = staticize(handler, method_self)

		if isinstance(key_name, int):
			self._keys[key_name] = handler
			return

		#alt buttons
		if key_name.lower().startswith("a-"):
			try:
				true_name = self._VALID_KEYNAMES[key_name[2:]]
				self._altkeys[true_name] = handler
			except KeyError:
				raise ValueError("key '%s' invalid" % key_name)
			return
		#mouse buttons
		if key_name.lower().startswith("mouse-"):
			try:
				true_name = self._MOUSE_BUTTONS[key_name[6:]]
				self._mouse[true_name] = handler
			except KeyError:
				raise ValueError("key '%s' invalid" % key_name)
			return
		if key_name.lower() == "mouse":
			self._mouse[-1] = handler
			return

		#everything else
		try:
			true_name = self._VALID_KEYNAMES[key_name]
			self._keys[true_name] = handler
		except:
			raise ValueError("key '%s' invalid" % key_name)

	def input(self, handler):
		'''
		Set a handler for any generic input (that doesn't have another handler)
		Will bind `handler` to a KeyMethod instance if it isn't already
		'''
		if not isinstance(handler, KeyMethod):
			handler = KeyMethod(handler)
		self._keys[-1] = handler

	def nomouse(self):
		'''Unbind the mouse from _keys'''
		if curses.KEY_MOUSE in self._keys:
			del self._keys[curses.KEY_MOUSE]

	def noalt(self):
		'''Unbind alt keys'''
		if 27 in self._keys:
			del self._keys[27]

	@classmethod
	def initialize_class(cls):
		for curse_name in dir(curses):
			if "KEY_" in curse_name:
				better_name = curse_name[4:].lower()
				#better name
				if better_name == "dc":
					better_name = "delete"
				if better_name in ("resize", "mouse"):
					continue
				elif better_name not in cls._VALID_KEYNAMES: #no remapping keys
					cls._VALID_KEYNAMES[better_name] = getattr(curses, curse_name)

		#simple command key names
		for no_print in range(32):
			#correct keynames for ^@ and ^_ (\x00 and \x1f), lowercase otherwise
			cls._VALID_KEYNAMES["^%s"%chr(no_print+64).lower()] = no_print
		for print_char in range(32, 127):
			cls._VALID_KEYNAMES[chr(print_char)] = print_char
		for mouse_button in cls._MOUSE_BUTTONS.values():
			cls.MOUSE_MASK |= mouse_button

	@classmethod
	def clone_key(cls, old, new):
		'''Redirect one key to another. DO NOT USE FOR VALUES IN range(32,128)'''
		try:
			if isinstance(old, str):
				old = cls._VALID_KEYNAMES[old]
			if isinstance(new, str):
				new = cls._VALID_KEYNAMES[new]
		except:
			raise ValueError("%s or %s is an invalid key name"%(old, new))
		cls._KEY_LUT[old] = new
KeyContainer.initialize_class()

def quitlambda():
	'''Close current overlay'''
	return -1

#DISPLAY CLASSES----------------------------------------------------------
class SizeException(Exception):
	'''
	Exception for errors when trying to display an overlay.
	Should only be raised in an overlay's resize method,
	where if raised, the Screen instance will not attempt to display.
	'''

class Box:
	'''
	Virtual class containing useful box shaping characters.
	Subclasses must also be subclasses of OverlayBase
	'''
	CHAR_HSPACE = '─'
	CHAR_VSPACE = '│'
	CHAR_TOPL = '┌'
	CHAR_TOPR = '┐'
	CHAR_BTML = '└'
	CHAR_BTMR = '┘'

	def box_format(self, left, string, right, justchar=' '):
		'''Format and justify part of box'''
		return "{}{}{}".format(left, self.box_just(string, justchar), right)

	def box_just(self, string, justchar=' '):
		'''Pad string by column width'''
		if not isinstance(self, OverlayBase):
			raise SizeException("cannot get width of box %s" % self.__name__)
		return string + justchar*(self.width-2-collen(string))

	def box_noform(self, string):
		'''Returns a string in the sides of a box. Does not pad spaces'''
		return self.CHAR_VSPACE + string + self.CHAR_VSPACE

	def box_part(self, fmt=''):
		'''Returns a properly sized string of the sides of a box'''
		return self.box_format(self.CHAR_VSPACE, fmt
			, self.CHAR_VSPACE)

	def box_top(self, fmt=''):
		'''Returns a properly sized string of the top of a box'''
		return self.box_format(self.CHAR_TOPL, fmt, self.CHAR_TOPR
			, self.CHAR_HSPACE)

	def box_bottom(self, fmt=''):
		'''Returns a properly sized string of the bottom of a box'''
		return self.box_format(self.CHAR_BTML, fmt, self.CHAR_BTMR
			, self.CHAR_HSPACE)

class _NScrollable(ScrollSuggest):
	'''
	A scrollable that expects a Screen as parent so that it
	can run Screen.update_input()
	'''
	def __init__(self, parent):
		super().__init__(parent.width)
		self.parent = parent

	def _onchanged(self):
		super()._onchanged()
		self.parent.update_input()

#OVERLAYS----------------------------------------------------------------------
class OverlayBase:
	'''
	Virtual class that redirects input to callbacks and modifies a list
	of (output) strings. All overlays must inherit from OverlayBase
	'''
	def __init__(self, parent):
		self.parent = parent		#parent
		self.index = None			#index in the stack
		self._left = None			#text to draw in reverse video
		self._right = None			#same but on the right side of the screen
		self.keys = KeyContainer()
		self.keys.screen_keys(parent)
		if hasattr(self, "_add_on_init"):
			self.add_keys(self._add_on_init, make_method=True)

	width = property(lambda self: self.parent.width)
	height = property(lambda self: self.parent.height)

	left = property(lambda self: self._left, doc="Left side display")
	@left.setter
	def left(self, new):
		self._left = new
		self.parent.update_status()

	right = property(lambda self: self._right, doc="Right side display")
	@right.setter
	def right(self, new):
		self._right = new
		self.parent.update_status()

	def __call__(self, lines):
		'''
		Virtual method called by Screen.display. It is supplied with a list
		of lines to be printed to the screen. Modify lines by item (i.e
		lines[value]) to display to the screen
		'''

	def run_key(self, chars):
		'''
		Run a key callback. This expects a single argument: a list of numbers
		terminated by -1. If the return value has boolean True, Screen will
		redraw; if the return value is -1, the overlay will remove itself
		'''
		if self.keys(chars) == -1:
			self.remove()
		return 1

	def resize(self, newx, newy):
		'''Virtual function called on all overlays in stack on resize event'''

	#frontend methods----------------------------
	def add(self):
		'''Finalize setup and add overlay'''
		#insensitive to being added again
		if self.index is None:
			self.parent.add_overlay(self)

	def remove(self):
		'''Finalize overlay and pop'''
		#insensitive to being removed again
		if self.index is not None:
			self.parent.pop_overlay(self)

	def swap(self, new):
		'''Pop overlay and add new one in succession.'''
		self.remove()
		new.add()

	def add_keys(self, new_functions, make_method=False):
		'''
		Add keys handlers from dict `new_functions`.
		Keys of `new_functions` must be raw character number, a valid keyname,
		a-[keyname] for Alt combination, ^[keyname] for Ctrl combination,
		or mouse-{right, left...} for mouse.
		Valid keynames are found in KeyContainer._VALID_KEYNAMES; usually curses
		KEY_* names, without KEY_, or the string of length 1 typed
		'''
		for i, j in new_functions.items():
			self.keys.add_key(i, j, method_self=(self if make_method else None))

	def key_handler(self, key_name, override_val=None, make_method=True):
		'''
		Decorator for adding a key handler.
		See add_keys documentation for valid values of `key_name`
		'''
		def ret(func):
			cook = func
			if override_val is not None:
				cook = override(func, override_val)
			self.keys.add_key(key_name, cook
				, method_self=(self if make_method else None))
			return func
		return ret

	@classmethod
	def add_on_init(cls, key):
		'''Decorator for adding keys on init. See add_handler for details'''
		if not hasattr(cls, "_add_on_init"):
			cls._add_on_init = {}
		def ret(func):
			cls._add_on_init[key] = func
			return func
		return ret

	@classmethod
	def add_keydoc(cls, keys, predicate=""):
		if not hasattr(cls, "_more_help"):
			cls._more_help = []
		cls._more_help.extend([predicate + i for i in dir(keys)])

	def _get_help_overlay(self):
		'''Get list of this overlay's keys'''
		from .overlay import ListOverlay, DisplayOverlay
		keys_list = dir(self.keys)
		if hasattr(self, "_more_help"):
			keys_list.extend(self._more_help)
		key_overlay = ListOverlay(self.parent, keys_list)

		@key_overlay.key_handler("enter")
		def get_help(me):
			docstring = me.list[me.it]
			help_display = DisplayOverlay(me.parent, docstring)
			help_display.add_key("enter", quitlambda)
			help_display.add()

		return key_overlay

	def open_help(self):
		'''Open help overlay'''
		self._get_help_overlay().add()

class TextOverlay(OverlayBase):
	'''Virtual overlay with text input (at bottom of screen)'''
	def __init__(self, parent=None):
		super().__init__(parent)
		self.text = _NScrollable(self.parent)
		#ASCII code of sentinel char
		self._sentinel = 0
		self.keys.input(self._input)

		self.add_keys({
			  "tab":		self.text.complete
			, '^d':			self.text.clear
			, "^z":			self.text.undo
			, "backspace":	self.text.backspace
			, "btab":		self.text.backcomplete
			, "delete":		self.text.delchar
			, "shome":		self.text.clear
			, "right":		staticize(self.text.movepos, 1
								, doc="Move cursor right")
			, "left":		staticize(self.text.movepos, -1
								, doc="Move cursor left")
			, "home":		self.text.home
			, "end":		self.text.end
			, 520:			self.text.delnextword
			, "a-h":		self.text.wordback
			, "a-l":		self.text.wordnext
			, "a-backspace":	self.text.delword
		})

	def resize(self, newx, newy):
		'''Adjust scrollable on resize'''
		self.text.setwidth(newx)

	def _input(self, chars):
		'''
		Appends to self.text, removing control characters. If self.text is
		empty and chars is a singleton of self._sentinel, then self._on_sentinel
		is fired instead.
		'''
		if self._sentinel and not str(self.text) and len(chars) == 1 and \
			chars[0] == self._sentinel:
			return self._on_sentinel()
		#allow unicode input with the bytes().decode()
		#take out characters that can't be decoded (i.e., those used by curses)
		buffer = bytes(filter(lambda x: x < 256, chars))
		if not buffer:
			return None
		return self.text.append(self._transform_paste(buffer.decode()))

	def _on_sentinel(self):
		'''Callback run when self._sentinel is typed and self.text is empty'''

	def _transform_paste(self, string):
		'''
		Transform input before appending to self.text. Must return the
		transformed string
		'''
		return string

	def control_history(self, history):
		'''Add standard key definitions for controls on History `history`'''
		nexthist = lambda: self.text.setstr(history.nexthist(str(self.text)))
		prevhist = lambda: self.text.setstr(history.prevhist(str(self.text)))
		#preserve docstrings for get_keynames
		nexthist.__doc__ = history.nexthist.__doc__
		prevhist.__doc__ = history.prevhist.__doc__
		self.add_keys({
			  "up":		nexthist
			, "down":	prevhist
		})

#OVERLAY MANAGER----------------------------------------------------------------
class Blurb:
	'''Screen helper class that manipulates the last two lines of the window.'''
	def __init__(self, parent):
		self.parent = parent

		self._erase = False
		self._refresh_task = None
		self.last = 0
		self.queue = []
		self.left = ""
		self.right = ""

	def _push(self, blurb, timestamp):
		'''Helper method to push blurbs and timestamp them'''
		#try to queue a blurb
		if blurb:
			if not isinstance(blurb, Coloring):
				blurb = Coloring(blurb)
			self.queue = blurb.breaklines(self.parent.width)
		#holding a message?
		if self.last < 0:
			return None
		#next blurb is either a pop from the last message or nothing
		if self.queue:
			blurb = self.queue.pop(0)
		else:
			blurb = ""
		self.last = timestamp
		return blurb

	def push(self, blurb=""):
		'''Pushes blurb to the queue and timestamps the transaction.'''
		ret = self._push(blurb, self.parent.loop.time())
		if ret is not None:
			self.parent.write_status(ret, 2)

	def hold(self, blurb):
		'''Holds blurb, preempting all `push`s until `release`'''
		self.parent.write_status(self._push(blurb, -1), 2)

	def release(self):
		'''Releases a `hold`. Needed to re-enable `push`'''
		self.last = self.parent.loop.time()
		self.parent.write_status(self._push("", self.last), 2)

	async def _refresh(self, time):
		'''Helper coroutine to start_refresh'''
		while self._erase:
			await asyncio.sleep(time)
			if self.parent.loop.time() - self.last > time: #erase blurbs
				self.push()

	def start_refresh(self, time):
		'''Start coroutine to advance blurb drawing every `time` seconds'''
		self._erase = True
		self._refresh_task = self.parent.loop.create_task(self._refresh(time))

	def end_refresh(self):
		'''Stop refresh coroutine'''
		self._erase = False
		if self._refresh_task is not None:
			self._refresh_task.cancel()

class Screen:
	'''
	Abstraction for interacting with the curses screen. Maintains overlays and
	handles I/O. Initialization also acquires and prepares the curses screen.
	'''
	_INTERLEAVE_DELAY = .001
	_INPUT_DELAY = .01

	_RETURN_CURSOR = "\x1b[?25h\x1b[u\n\x1b[A"
	#return cursor to the top of the screen, hide, and clear formatting on drawing
	_DISPLAY_INIT = "\x1b[;f%s\x1b[?25l" % CLEAR_FORMATTING
	#format with tuple (row number, string)
	#move cursor, clear formatting, print string, clear garbage, and return cursor
	_SINGLE_LINE = "\x1b[%d;f" + CLEAR_FORMATTING +"%s\x1b[K" + _RETURN_CURSOR
	_RESERVE_LINES = 3

	def __init__(self, manager, refresh_blurbs=True, loop=None):
		if not (sys.stdin.isatty() and sys.stdout.isatty()):
			raise OSError("interactive stdin/stdout required for Screen")
		self.manager = manager
		self.loop = asyncio.get_event_loop() if loop is None else loop

		self.active = True
		self._candisplay = False
		#guessed terminal dimensions
		self.width = 40
		self.height = 30
		#input/display stack
		self._ins = []
		#last high-priority overlay
		self._last_replace = 0
		self._last_text = -1

		self.blurb = Blurb(self)
		if refresh_blurbs:
			self.blurb.start_refresh(4)

		#redirect stdout
		self._displaybuffer = sys.stdout
		sys.stdout = open(_REDIRECTED_OUTPUT, "a+", buffering=1)
		if sys.stderr.isatty():
			sys.stderr = sys.stdout

		#escape has delay, not that this matters since I use tmux frequently
		os.environ.setdefault("ESCDELAY", "25")
		#pass in the control chars for ctrl-c and ctrl-z
		loop.add_signal_handler(SIGINT, lambda: curses.ungetch(3))
		loop.add_signal_handler(SIGTSTP, lambda: curses.ungetch(26))

		#curses input setup
		self._screen = curses.initscr()		#init screen
		curses.noecho(); curses.cbreak(); self._screen.keypad(1) #setup curses
		self._screen.nodelay(1)	#don't wait for enter to get input
		self._screen.getch() #the first getch clears the screen

	def shutdown(self):
		'''Remove all overlays and undo everything in enter'''
		self.blurb.end_refresh()
		#let overlays do cleanup
		try:
			for i in reversed(self._ins):
				i.remove()
		except:
			print("Error occurred during shutdown:")
			print(traceback.format_exc(), "\n")
		finally:
			#return to sane mode
			curses.echo(); curses.nocbreak(); self._screen.keypad(0)
			curses.endwin()
			sys.stdout.close() #close the temporary buffer set up
			sys.stdout = self._displaybuffer #reconfigure output
			sys.stderr = sys.stdout

			self.loop.remove_signal_handler(SIGINT)
			self.loop.remove_signal_handler(SIGTSTP)

	def sound_bell(self):
		'''Sound console bell.'''
		self._displaybuffer.write('\a')

	def toggle_mouse(self, state):
		'''Turn the mouse on or off'''
		if not (self.active and self._candisplay):
			return None
		return curses.mousemask(state and KeyContainer.MOUSE_MASK)

	#Display Methods------------------------------------------------------------
	async def resize(self):
		'''Fire all added overlay's resize methods'''
		newy, newx = self._screen.getmaxyx()
		#some terminals don't like drawing the last column
		if os.getenv("TERM") == "xterm":
			newx -= 1
		#magic number, but who cares; lines for text, blurbs, and reverse info
		newy -= self._RESERVE_LINES
		try:
			for i in self._ins:
				i.resize(newx, newy)
				await asyncio.sleep(self._INTERLEAVE_DELAY)
			self.width, self.height = newx, newy
			self._candisplay = 1
			self.update_input()
			self.update_status()
			await self.display()
		except SizeException:
			self.width, self.height = newx, newy
			self._candisplay = 0

	async def display(self):
		'''
		Draws the highest overlays (with stack indices greater than
		_last_replace)
		'''
		if not (self.active and self._candisplay and self.height > 0):
			if self.active:
				self._displaybuffer.write("RESIZE TERMINAL")
			return
		#justify number of lines
		lines = ["" for i in range(self.height)]
		try:
		#start with the last "replacing" overlay, then all overlays afterward
			for start in range(self._last_replace, len(self._ins)):
				self._ins[start](lines)
				await asyncio.sleep(self._INTERLEAVE_DELAY)
		except SizeException:
			self._candisplay = 0
			return
		self._displaybuffer.write(self._DISPLAY_INIT)
		#draw each line in lines, deleting the rest of the garbage on the line
		for i in lines:
			self._displaybuffer.write(i+"\x1b[K\n\r")
		self._displaybuffer.write(self._RETURN_CURSOR)

	def schedule_display(self):
		self.loop.create_task(self.display())

	def schedule_resize(self):
		self.loop.create_task(self.resize())

	def update_input(self):
		'''Input display backend'''
		if not (self.active and self._candisplay):
			return
		if self._last_text < 0:
			return	#no textoverlays added
		string = format(self._ins[self._last_text].text)
		self._displaybuffer.write(self._SINGLE_LINE %
			(self.height+1, string))

	def update_status(self):
		'''Look for the highest blurb for which status has been set'''
		room = self.width
		left = ""
		right = ""
		for i in reversed(self._ins):
			if i.left is not None or i.right is not None:
				left = i.left or left
				right = i.right or right
				room -= collen(left) + collen(right)
				if room < 1:
					#don't even bother. update_status is run from places that might not tolerate an exception
					return
				break
		self.write_status("\x1b[7m{}{}{}\x1b[m".format(left,
			' '*room, right), 3)

	def write_status(self, string, height):
		if not (self.active and self._candisplay):
			return
		self._displaybuffer.write(self._SINGLE_LINE %
			(self.height+height, string))

	def redraw_all(self):
		'''Force redraw'''
		self.schedule_display()
		self.blurb.push()
		self.update_input()
		self.update_status()

	#Overlay Backends-----------------------------------------------------------
	def add_overlay(self, new):
		'''Add overlay backend. Use overlay.add() instead.'''
		if not isinstance(new, OverlayBase):
			return
		new.index = len(self._ins)
		self._ins.append(new)
		if new.replace:
			self._last_replace = new.index
		if isinstance(new, TextOverlay):
			self._last_text = new.index
			self.update_input()
		#display is not strictly called beforehand, so better safe than sorry
		self.schedule_display()
		self.update_status()

	def pop_overlay(self, overlay):
		'''Pop overlay backend. Use overlay.remove() instead.'''
		del self._ins[overlay.index]
		#look for the last replace and replace indices
		was_replace = overlay.index == self._last_replace
		was_text = overlay.index == self._last_text
		for i, j in enumerate(self._ins):
			if j.replace and was_replace:
				self._last_replace = i
			if isinstance(j, TextOverlay) and was_text:
				self._last_text = i
				self.update_input()
			j.index = i
		if self._last_text == overlay.index:
			self._last_text = -1
		overlay.index = None
		self.schedule_display()
		self.update_status()

	#Overlay Frontends----------------------------------------------------------
	def get_overlay(self, index):
		'''
		Get an overlay by its index in self._ins. Returns None
		if index is invalid
		'''
		if self._ins and index < len(self._ins):
			return self._ins[index]
		return None

	def get_overlays_by_class_name(self, name, highest=0):
		'''
		Like getElementsByClassName in a browser.
		Returns a list of Overlays with the class name `name`
		'''
		#use string __name__s in case scripts can't get access to the method
		if isinstance(name, type):
			name = name.__name__
		#limit the highest index
		if not highest:
			highest = len(self._ins)

		ret = []
		for i in range(highest):
			overlay = self._ins[i]
			#respect inheritence
			if name in [j.__name__ for j in type(overlay).mro()]:
				ret.append(overlay)
		return ret

	#Loop Coroutines------------------------------------------------------------
	async def input(self):
		'''
		Wait (non-blocking) for character, then run an overlay's key handler.
		If the key handler returns -1, the overlay is removed. If it returns
		something equivalent to boolean True, re-displays the screen.
		'''
		nextch = -1
		while nextch == -1:
			nextch = self._screen.getch()
			await asyncio.sleep(self._INPUT_DELAY)

		#capture ctrl-c
		if nextch == 3:
			self.active = False
			return

		#we need this here so that _input doesn't lock up the rest of the loop
		#and we return to the event loop at least once with `await sleep`;
		if not self._ins:
			return

		chars = [nextch]
		while nextch != -1:
			nextch = self._screen.getch()
			chars.append(nextch)
		ret = self._ins[-1].run_key(chars)

		if ret:
			await self.display()

	def stop(self):
		self.active = False
		#if input is running, this gets it out of the await loop
		curses.ungetch(0)

class Manager:
	'''Main class; creates a screen and maintains graceful exits'''
	last = 0
	_on_exit = []
	def __init__(self, loop=None):
		loop = asyncio.get_event_loop() if loop is None else loop
		if not hasattr(loop, "create_future"):
			setattr(loop, "create_future", lambda: asyncio.Future(loop=self.loop))
		self.loop = loop
		#general state
		self.exited = asyncio.Event(loop=loop)

		self.screen = None

	async def run(self, prepared_coroutine=None, refresh_blurbs=True):
		'''Main client loop'''
		try:
			self.screen = Screen(self, refresh_blurbs=refresh_blurbs, loop=self.loop)
			await self.screen.resize()
			if prepared_coroutine is not None:
				await prepared_coroutine

			#done for now; call coroutines waiting for preparation
			while self.screen.active:
				await self.screen.input()
		except asyncio.CancelledError:
			pass	#catch cancellations
		finally:
			for i in self._on_exit:
				await i
			self.screen.shutdown()
			self.screen = None
			self.exited.set()

	@classmethod
	def start(cls, *args, loop=None):
		'''
		Create an instance of the Manager() class and return the instance.
		Further arguments are interpreted as func, arg0, arg1,... and called
		when the manager is prepared with `func(Manager, arg0, arg1,...)`
		'''
		#instantiate
		this, prepared_coroutine = cls(loop=loop), None
		try:
			#just use the first arg as a function
			if args and callable(args[0]):
				if not asyncio.iscoroutinefunction(args[0]):
					raise TypeError("Expected coroutine as first argument to "\
						"Manager.start")
				prepared_coroutine = args[0](this, *args[1:])

			this.loop.create_task(this.run(prepared_coroutine))
			#wait for the loop to exit
			this.loop.run_until_complete(this.exited.wait())
		finally:
			if this.screen is not None:
				this.screen.shutdown()
			this.loop.run_until_complete(this.loop.shutdown_asyncgens())

	def stop(self):
		if self.screen is not None:
			self.screen.stop()

	#Miscellaneous Frontends----------------------------------------------------
	@classmethod
	def on_done(cls, func, *args):
		'''
		Add function or prepared coroutine to be run after the Manager
		instance has shut down
		'''
		if asyncio.iscoroutinefunction(func):
			raise TypeError("Coroutine, not coroutine object, passed into on_done")
		elif not asyncio.iscoroutine(func):
			func = asyncio.coroutine(func)(*args)
		cls._on_exit.append(func)
		return func
