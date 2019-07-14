#!/usr/bin/env python3
#client.overlay.py
'''
Overlays that allow multiple input formats. Also includes InputMux, which
provides a nice interface for modifying variables within a context.
'''
import asyncio
from .display import SELECT, CLEAR_FORMATTING, raw_num, get_color \
	, Coloring, JustifiedColoring, DisplayException
from .base import staticize, override, quitlambda \
	, Box, OverlayBase, TextOverlay, SizeException

__all__ = [
	  "Box", "OverlayBase", "ListOverlay", "VisualListOverlay", "ColorOverlay"
	, "ColorSliderOverlay", "ConfirmOverlay", "DisplayOverlay", "InputMux"
]

def _search_cache(keys, value):
	'''Search through an iterable for value that equals `value` and return it'''
	for i in keys:
		if i == value:
			return i
	return value

#DISPLAY CLASSES----------------------------------------------------------
class ListOverlay(OverlayBase, Box):
	'''
	Allows user to select an entry from a list.
	By default, the list is cloned, but any other callable returning a list can
	be specified with the `builder` argument
	The display of each entry can be altered with the `line_drawer` decorator.
	'''
	replace = True
	def __init__(self, parent, out_list, modes=None, builder=list, refresh_on_input=False):
		super().__init__(parent)
		self._it = 0
		self.mode = 0

		self.raw, self._builder = out_list, builder
		self.list = builder(self.raw)

		self._draw_other = None
		self._modes = [""] if modes is None else modes
		self._search = None
		self._draw_cache = set()

		up =	staticize(self.increment, -1,
			doc="Up one list item")
		down =	staticize(self.increment, 1,
			doc="Down one list item")
		right =	staticize(self.chmode, 1,
			doc=("Go to next mode" if modes is not None else None))
		left =	staticize(self.chmode, -1,
			doc=("Go to previous mode" if modes is not None else None))

		def try_enter():
			'''Run enter (if it exists)'''
			enter_fun = self._keys.get(10)
			if callable(enter_fun):
				return enter_fun()
			return None

		def click(_, y):
			'''Run enter on the element of the list that was clicked'''
			#Manipulate self.it and try_enter
			#y in the list
			size = self.height - 2
			#borders
			if not y in range(1, size+1):
				return None
			newit = (self.it//size)*size + (y - 1)
			if newit >= len(self.list):
				return None
			self.it = newit
			return try_enter()

		self.add_keys({
			  "^r":		self.regen_list
			, 'j':		down	#V I M
			, 'k':		up
			, 'l':		right
			, 'h':		left
			, 'H':		self.open_help
			, 'g':		staticize(self.goto_edge, 0, doc="Go to list beginning")
			, 'G':		staticize(self.goto_edge, 1, doc="Go to list end")
			, '/':		self.open_search
			, "^f":		self.open_search
			, "n":		staticize(self.scroll_search, 1)
			, "N":		staticize(self.scroll_search, 0)
			, 'q':		quitlambda
			, "backspace":	self.clear_search
			, "down":	down
			, "up":		up
			, "right":	right
			, "left":	left
			, "mouse-left":			click
			, "mouse-right":		override(click)
			, "mouse-middle":		try_enter
			, "mouse-wheel-up":		up
			, "mouse-wheel-down":	down
		})

	it = property(lambda self: self._it
		, doc="Currently selected list index")
	@it.setter
	def it(self, dest):
		self._do_move(dest)

	search = property(lambda self: self._search
		, doc="Current string to search with nN")
	@search.setter
	def search(self, new):
		status = ""
		if new:
			status = '/' + new
		else:
			new = None
		self.parent.write_status(status, 1)
		self._search = new

	@property
	def selected(self):
		'''The currently selected element from self.list.'''
		return self.list[self.it]

	def remove(self):
		super().remove()
		self.parent.update_input()

	def __getitem__(self, val):
		'''Sugar for `self.list[val]`'''
		return self.list[val]

	def __iter__(self):
		'''Sugar for `iter(self.list)`'''
		return iter(self.list)

	def __call__(self, lines):
		'''
		Display a list in a box. If too long, entries are trimmed
		to include an ellipsis
		'''
		lines[0] = self.box_top()
		size = self.height-2
		maxx = self.width-2
		#worst case column: |(value[0])…(value[-1])|
		#				    1    2     3  4        5
		#worst case rows: |(list member)|(RESERVED)
		#				  1	2			3
		if size < 1 or maxx < 3:
			raise SizeException()
		#which portion of the list is currently displaced
		partition = self.it - (self.it%size)
		#get the partition of the list we're at, pad the list
		sub_list = self.list[partition:partition+size]
		sub_list = sub_list + ["" for i in range(size-len(sub_list))]
		#display lines
		for i, row in enumerate(sub_list):
			if not isinstance(row, JustifiedColoring):
				row = JustifiedColoring(str(row))
			#alter the string to be drawn
			if i+partition < len(self.list):
				self._draw_line(row, i+partition)
			row = _search_cache(self._draw_cache, row)
			#draw the justified string
			lines[i+1] = self.box_noform(row.justify(maxx))
			#and cache it
			self._draw_cache.add(row)

		lines[-1] = self.box_bottom(self._modes[self.mode])
		return lines

	def line_drawer(self, func):
		'''
		Decorator to set a line drawer. Must have signature (self, line,
		, number), where `line` is a Coloring object of a line and `number`
		is its index in self.list
		'''
		self._draw_other = func

	def _draw_line(self, line, number):
		'''Callback to run to modify display of each line. '''
		if self._draw_other is not None:
			self._draw_other(self, line, number)
		if number == self.it:	#reverse video on selected line
			line.add_global_effect(0)

	def _do_move(self, dest):
		'''
		Callback for setting property 'it'. Useful for when an update is needed
		self.it changes (like VisualListOverlay)
		'''
		self._it = dest

	#predefined list iteration methods
	def increment(self, amt):
		'''Move self.it by amt'''
		if not self.list:
			return
		self.it = (self.it + amt) % len(self.list)

	def chmode(self, amt):
		'''Move to mode amt over, with looparound'''
		self.mode = (self.mode + amt) % len(self._modes)

	def goto_edge(self, is_end):
		'''Move to the beginning or end of the list'''
		self.it = int(is_end and (len(self.list)-1))

	def _goto_lambda(self, func, direction, loop=False):
		'''
		Backend for goto_lambda.
		`direction` = 0 for closer to the top, 1 for closer to the bottom.
		'''
		start = self.it
		for i in range(len(self.list)-start-1 if direction else start):
			i = (start+i+1) if direction else (start-i-1)
			if func(i):
				self.it = i
				return
		if loop:
			for i in range(start if direction else len(self.list)-start-1):
				i = i if direction else len(self.list)-i-1
				if func(i):
					self.it = i
					return
		else:
			self.it = int(direction and (len(self.list)-1))

	def goto_lambda(self, func):
		'''
		Move to a list entry for which `func` returns True.
		`func`'s signature should be (self.list index)
		'''
		return tuple(staticize(self._goto_lambda, func, i) for i in range(2))

	def regen_list(self):
		'''Regenerate list based on raw list reference'''
		if self.raw:
			self.list = self._builder(self.raw)

	def open_search(self):
		'''Open a search window'''
		search = InputOverlay(self.parent)
		search.text.setnonscroll('/')
		def callback(value):
			self.search = str(value)
			self.scroll_search(1)
		search.callback(callback)
		search.add()

	def clear_search(self):
		'''Clear search'''
		self.search = ""

	def scroll_search(self, direction):
		'''Scroll through search index'''
		def goto(index):
			value = self.list[index]
			if isinstance(value, str) and self.search is not None:
				return value.lower().find(self.search.lower()) != -1
			return False
		self._goto_lambda(goto, direction, True)

class VisualListOverlay(ListOverlay, Box):
	'''ListOverlay with visual mode like in vim: can select multiple rows'''
	replace = True
	def __init__(self, parent, *args, **kwargs):
		super().__init__(parent, *args, **kwargs)
		self._selected = set()
		self._select_buffer = set()
		self._start_select = -1

		self.add_keys({
			  'q':	self.clear_quit
			, 's':	self.toggle
			, 'v':	self.toggle_select
		})

	@property
	def current(self):
		'''Sugar more similar to `ListOverlay.selected`'''
		return self.list[self.it]

	@property
	def selected(self):
		'''Get list of selected items'''
		indices = self._selected_index()
		#add the iterator; idempotent if already in set
		#here so that the currently selected line doesn't draw an underline
		indices.add(self.it)
		return [self.list[i] for i in indices]

	def _do_move(self, dest):
		'''Update selection'''
		if self._start_select + 1:
			if dest < self._start_select:	#selecting below start
				self._select_buffer = set(range(dest, self._start_select))
			else:
				self._select_buffer = set(range(self._start_select+1, dest+1))
		self._it = dest

	def _draw_line(self, line, number):
		'''New draw callback that adds an underline to selected elements'''
		super()._draw_line(line, number)
		if number in self._selected_index():
			line.add_global_effect(1)

	def clear(self):
		self._selected = set()	#list of indices selected by visual mode
		self._select_buffer = set()
		self._start_select = -1

	def toggle(self):
		'''Toggle the current line'''
		self._selected.symmetric_difference_update((self.it,))

	def toggle_select(self):
		'''Toggle visual mode selecting'''
		if self._start_select + 1:	#already selecting
			#canonize the select
			self._selected.symmetric_difference_update(self._select_buffer)
			self._select_buffer = set()
			self._start_select = -1
			return
		self.toggle()
		self._start_select = self.it

	def _selected_index(self):
		'''Get list (set) of selected and buffered indices'''
		return self._selected.symmetric_difference(self._select_buffer)

	def clear_quit(self):
		'''Clear the selection or quit the overlay'''
		if self._select_buffer or self._selected:
			return self.clear()
		return -1

class ColorOverlay(ListOverlay, Box):
	'''Display 3 bars for red, green, and blue. Allows exporting of color as hex'''
	replace = True
	_SELECTIONS = ["normal", "shade", "tint", "grayscale"]
	_COLOR_LIST = ["red", "orange", "yellow", "light green", "green", "teal",
		"cyan", "turquoise", "blue", "purple", "magenta", "pink", "color sliders"]

	def __init__(self, parent, initcolor=None):
		self._spectrum = self._genspectrum()
		super().__init__(parent, self._COLOR_LIST, self._SELECTIONS)
		self.initcolor = [127, 127, 127]
		self._callback = None

		#parse initcolor
		if isinstance(initcolor, str) and len(initcolor) == 6:
			initcolor = [int(initcolor[i*2:(i+1)*2], 16) for i in range(3)]
		if isinstance(initcolor, list) and len(initcolor) == 3:
			self.initcolor = initcolor
			#how much each color corrseponds to some color from the genspecturm
			divs = [divmod(i*5/255, 1) for i in initcolor]
			#if each error is low enough to be looked for
			if all(i[1] < .05 for i in divs):
				for i, j in enumerate(self._spectrum[:3]):
					try:
						find = j.index(tuple(int(k[0]) for k in divs))
						self.it = find
						self.mode = i
						break
					except ValueError:
						pass
			else:
				self.it = len(self._COLOR_LIST)-1
		self.add_keys({
			  'tab':	self._select
			, 'enter':	self._select
			, ' ':	self._select
		})

	def _select(self):
		'''Open the sliders or run the callback with the selected color'''
		if self.it == 12:
			return self.open_sliders()
		return self._callback(self.color)

	def callback(self, callback):
		'''
		Set callback when color is selected. Callback should have signature
		(color), where `color` is a RGB 3-tuple
		'''
		self._callback = callback

	def _draw_line(self, string, i):
		'''Add color samples to the end of lines'''
		super()._draw_line(string, i)
		#reserved for color sliders
		if i == len(self._COLOR_LIST)-1 or not self.parent.two56:
			return
		which = self._spectrum[self.mode][i]
		if self.mode == 3: #grayscale
			color = self.parent.two56.grayscale(i * 2)
		else:
			color = self.parent.two56([i*255/5 for i in which])
		try:
			string.add_indicator(' ', color, 0)
		except DisplayException:
			pass

	@property
	def color(self):
		'''Retrieve color as RGB 3-tuple'''
		which = self._spectrum[self.mode][self.it]
		if self.mode == 3:
			return (255 * which/ 12 for i in range(3))
		return tuple(int(i*255/5) for i in which)

	def open_sliders(self):
		'''Swap with a ColorSliderOverlay and defer callback'''
		further_input = ColorSliderOverlay(self.parent, self.initcolor)
		further_input.callback(self._callback)
		self.swap(further_input)

	@staticmethod
	def _genspectrum():
		'''
		Create colors that correspond to values of _COLOR_LIST, as well as
		as tints, shades, and 12-step-grayscale
		'''
		init = [0, 2]
		final = [5, 2]
		rspec = [(5, g, 0) for g in init]
		yspec = [(r, 5, 0) for r in final]
		cspec = [(0, 5, b) for b in init]
		bspec = [(0, g, 5) for g in final]
		ispec = [(r, 0, 5) for r in init]
		mspec = [(5, 0, b) for b in final]

		#flatten spectra
		spectrum = [item for i in (rspec, yspec, cspec, bspec, ispec, mspec)
			for item in i]

		shade = [(max(0, i[0]-1), max(0, i[1]-1), max(0, i[2]-1))
			for i in spectrum]
		tint = [(min(5, i[0]+1), min(5, i[1]+1), min(5, i[2]+1))
			for i in spectrum]
		grayscale = range(12)

		return [spectrum, shade, tint, grayscale]

class ColorSliderOverlay(OverlayBase, Box):
	'''Display 3 bars for red, green, and blue.'''
	replace = True
	NAMES = ["Red", "Green", "Blue"]

	def __init__(self, parent, initcolor=None):
		super().__init__(parent)
		initcolor = initcolor if initcolor is not None else [127, 127, 127]
		if not isinstance(initcolor, (tuple, list)):
			raise TypeError("initcolor must be list or tuple")
		self.color = initcolor.copy()
		self._update_text()
		self._rgb = 0
		self._callback = None

		increase = staticize(self.increment, 1)
		decrease = staticize(self.increment, -1)

		next_bar = staticize(self.chmode, 1)
		prev_bar = staticize(self.chmode, -1)

		self.add_keys({
			  'enter':	self._select
			, 'q':		quitlambda
			, 'k':		increase
			, 'j':		decrease
			, 'l':		next_bar
			, 'h':		prev_bar
			, 'up':		increase
			, 'down':	decrease
			, 'ppage':	staticize(self.increment, 10)
			, 'npage':	staticize(self.increment, -10)
			, "home":	staticize(self.increment, 255)
			, "end":	staticize(self.increment, -255)
			, "right":	next_bar
			, "left":	prev_bar
		})

	def __call__(self, lines):
		'''Display 3 bars, their names, values, and string in hex'''
		wide = (self.width-2)//3 - 1
		space = self.height-7
		if space < 1 or wide < 5: #green is the longest name
			raise SizeException()
		lines[0] = self.box_top()
		for i in range(space):
			string = ""
			#draw on this line (ratio of space = ratio of value to 255)
			for j in range(3):
				if (space-i)*255 < (self.color[j]*space):
					string += get_color(raw_num(j+2))
				string += ' ' * wide + CLEAR_FORMATTING + ' '
			#justify (including escape sequence length)
			lines[i+1] = self.box_noform(self.box_just(string))
		sep = self.box_part("")
		lines[-6] = sep
		names, vals = "", ""
		for i in range(3):
			if i == self._rgb:
				names += SELECT
				vals += SELECT
			names += self.NAMES[i].center(wide) + CLEAR_FORMATTING
			vals += str(self.color[i]).center(wide) + CLEAR_FORMATTING
		lines[-5] = self.box_part(names) #4 lines
		lines[-4] = self.box_part(vals) #3 line
		lines[-3] = sep #2 lines
		lines[-2] = self.box_part(format(self._colored_text).rjust(int(wide*1.5)+3)) #1
		lines[-1] = self.box_bottom() #last line

	def _select(self):
		'''Run callback'''
		return self._callback(tuple(self.color))

	def callback(self, callback):
		self._callback = callback

	#predefined self-traversal methods
	def increment(self, amt):
		'''Increase the selected color by amt'''
		self.color[self._rgb] = max(0, min(255, self.color[self._rgb] + amt))
		self._update_text()

	def chmode(self, amt):
		'''Go to the color amt to the right'''
		self._rgb = (self._rgb + amt) % 3

	def _update_text(self):
		self._colored_text = Coloring(self.to_hex(self.color))
		self._colored_text.insert_color(0, self.parent.two56(self.color))

	@staticmethod
	def to_hex(color):
		'''Get color in hex form'''
		return ''.join("{:02X}".format(int(i)) for i in color)

class InputOverlay(TextOverlay, Box):
	'''
	An overlay to retrieve input from the user.
	Can either use `await this.result` or set a callback with `callback`
	'''
	replace = False
	def __init__(self, parent, prompt=None, password=False, default=""):
		super().__init__(parent)
		self._future = parent.loop.create_future()
		self._callback = None

		if prompt is None:
			self._prompt, self._prompts = None, []
		else:
			self._prompt = prompt if isinstance(prompt, Coloring) \
				else Coloring(prompt)
			self._prompts = self._prompt.breaklines(self.width-2)

		self.text.setstr(default)
		self.text.password = password
		self.add_keys({
			  '^d':	quitlambda
			, '^w':	quitlambda
			, 10:	self._finish
			, 127:	self._wrap_backspace
		})

	result = property(lambda self: self._future)

	def __call__(self, lines):
		'''Display the prompt in a box roughly in the middle'''
		if self._prompt is None:
			return
		start = self.height//2 - len(self._prompts)//2
		end = self.height//2 + len(self._prompts)
		if start+len(self._prompts) > self.height:
			lines[start] = self._prompts[0][:-1] + JustifiedColoring._ELLIPSIS
		lines[start] = self.box_top()
		for i, j in enumerate(self._prompts):
			lines[start+i+1] = self.box_part(j)
		#preserve the cursor position save
		lines[end+1] = self.box_bottom()

	def resize(self, newx, newy):
		'''Resize prompts'''
		super().resize(newx, newy)
		self._prompts = self._prompt.breaklines(self.width-2)

	def _wrap_backspace(self):
		'''Backspace a char, or quit out if there are no chars left'''
		if not str(self.text):
			return -1
		return self.text.backspace()

	def _finish(self):
		'''Regular stop (i.e, with enter)'''
		self._future.set_result(str(self.text))
		return -1

	def remove(self):
		'''Cancel future unless future completed'''
		if not self._future.done():
			self._future.cancel()
		super().remove()

	def callback(self, func):
		'''Attach a callback to the future'''
		def ret(future):
			if future.cancelled():
				return
			if asyncio.iscoroutinefunction(func):
				self.parent.loop.create_task(func(future.result()))
			else:
				func(future.result())
		self._future.add_done_callback(ret)

class DisplayOverlay(OverlayBase, Box):
	'''Overlay that displays a message in a box'''
	def __init__(self, parent, strings, outdent=""):
		super().__init__(parent)
		self._outdent = outdent

		self._rawlist = []
		self._formatted = []
		self.replace = False
		self._begin = 0
		self.change_display(strings)

		up = staticize(self.scroll, -1, doc="Scroll downward")
		down = staticize(self.scroll, 1, doc="Scroll upward")

		self.add_keys({
			  'k':		up
			, 'j':		down
			, 'q':		quitlambda
			, 'H':		self.open_help
			, "up":		up
			, "down":	down
		})

	def __call__(self, lines):
		'''Display message'''
		begin = max((self.height-2)//2 - len(self._formatted)//2, 0) \
			if not self.replace else 0
		i = 0
		lines[begin] = self.box_top()
		for i in range(min(len(self._formatted), len(lines)-2)):
			lines[begin+i+1] = self.box_part(self._formatted[self.begin+i])
		if self.replace:
			while i < len(lines)-3:
				lines[begin+i+2] = self.box_part("")
				i += 1
		lines[begin+i+2] = self.box_bottom()

	def resize(self, newx, newy):
		'''Resize message'''
		self._formatted = [j for i in self._rawlist
			for j in i.breaklines(self.width-2, outdent=self._outdent)]
		# if bigger than the box holding it, stop drawing the overlay behind it
		self.replace = len(self._formatted) > self.height-2

	def change_display(self, strings):
		'''Basically re-initialize without making a new overlay'''
		if isinstance(strings, (str, Coloring)):
			strings = [strings]
		self._rawlist = [i if isinstance(i, Coloring) else Coloring(i)
			for i in strings]

		#flattened list of broken strings
		self._formatted = [j	for i in self._rawlist
			for j in i.breaklines(self.width-2, outdent=self._outdent)]
		#bigger than the box holding it
		self.replace = len(self._formatted) > self.height-2

		self.begin = 0	#begin from this prompt

	def set_outdent(self, outdent):
		self._outdent = outdent

	def scroll(self, amount):
		maxlines = self.height-2
		if len(self._formatted) <= maxlines:
			return
		self.begin = min(max(0, self.begin+amount), maxlines-len(self._formatted))

class TabOverlay(OverlayBase):
	'''
	Overlay for 'tabbing' through things.
	Displays options on lines nearest to the input scrollable
	'''
	def __init__(self, parent, lis, callback=None, start=0, rows=5):
		super().__init__(parent)
		self.list = lis
		self.it = min(start, len(self.list)-1)
		self._rows = min(len(self.list), rows, self.height)
		self.replace = self._rows == self.height
		self.callback = callback

		self.add_keys({
			 -1:		self.remove
			, "tab":	staticize(self.move_it, 1)
			, "btab":	staticize(self.move_it, -1)
		})

	def __call__(self, lines):
		'''Display message'''
		line_offset = 1
		for i, entry in zip(range(self._rows), (self.list + self.list)[self.it:]):
			entry = Coloring(entry)
			#entry.insert_color(0, raw_num(7))
			entry.add_global_effect(1)
			if i == 0:
				entry.add_global_effect(0)
			formatted = entry.breaklines(self.width, "  ")
			for j, line in enumerate(reversed(formatted)):
				lines[-line_offset-j] = line
			line_offset += len(formatted)

	def add(self):
		'''If list is too small, exit early. Run callback on nonempty list'''
		if self.list:
			self.callback(self.list[self.it])
		if len(self.list) < 2:
			return
		super().add()

	def move_it(self, direction):
		self.it = (self.it + direction) % len(self.list)
		if callable(self.callback):
			self.callback(self.list[self.it])

class ConfirmOverlay(OverlayBase):
	'''Overlay to confirm selection y/n (no slash)'''
	replace = False
	def __init__(self, parent, prompt, callback):
		super().__init__(parent)
		self._prompt = prompt

		def call():
			if asyncio.iscoroutine(callback):
				self.parent.loop.create_task(callback)
			else:
				self.parent.loop.call_soon(callback)
			self.parent.blurb.release()
			return -1

		self._keys.update({ #run these in order
			  ord('y'):	call
			, ord('n'):	override(staticize(self.parent.blurb.release), -1)
		})
		self.nomouse()
		self.noalt()

	def add(self):
		'''Hold prompt blurb'''
		self.parent.blurb.hold(self._prompt)
		super().add()

#INPUTMUX CLASS-----------------------------------------------------------------
class InputMux:
	'''
	Abstraction for a set of adjustable values to display with a ListOverlay.
	Comes pre-built with drawing for each kind of value.
	'''
	def __init__(self, confirm_if_button=True):
		self.parent = None

		self.ordering = []
		self.indices = {}
		self.context = None
		self.confirm_if_button = confirm_if_button
		self.has_button = False
		self.warn_exit = False

	def add(self, parent, context):
		'''Add the muxer with ChatangoOverlay `parent`'''
		self.context = context
		self.parent = parent
		overlay = ListOverlay(parent
			, [self.indices[i].doc for i in self.ordering])
	
		overlay.line_drawer(self._drawing)

		@overlay.key_handler("tab", True)
		@overlay.key_handler("enter", True)
		@overlay.key_handler(' ', True)
		def select_sub(me):
			"Change value"
			return self.indices[self.ordering[me.it]].select()

		overlay.add_keys({
			'q':	staticize(self.try_warn, parent, overlay
				, doc=quitlambda.__doc__)
		})

		overlay.add()

	def _drawing(self, _, string, i):
		'''Defer to the _ListEl's local drawer'''
		element = self.indices[self.ordering[i]]
		#needs a drawer and a getter
		if element.draw and element.get:
			element.draw(self, element.get(self.context), string)

	class _ListEl:
		'''
		Decorator to create an input field with a certain data type.
		dataType can be one of "str", "color", "enum", "bool", or "button"
		The __init__ is akin to a `@property` decorator: as a getter;
		subsequent setters and drawers can be added from the return value
		(bound to func.__name__); i.e. `@func.setter...`

		func should have signature:
			(context:	the context as supplied by the InputMux)
		The name of the field in the list will be derived from func.__doc__
		'''
		def __init__(self, parent, data_type, func):
			self.name = func.__name__
			if parent.indices.get(self.name):
				raise TypeError("Cannot implement element {} more " \
					"than once".format(repr(self.name)))
			#bind parent names
			self.parent = parent
			self.parent.indices[self.name] = self
			self.parent.ordering.append(self.name)
			self.doc = func.__doc__

			self._type = data_type
			if self._type == "color":
				self.draw = self.draw_color
			elif self._type == "str":
				self.draw = self.draw_string
			elif self._type == "enum":
				self.draw = self.draw_enum
			elif self._type == "bool":
				self.draw = self.draw_bool
			elif self._type == "button":
				self.draw = None
				self.get = None
				self._set = func
				if self.parent.confirm_if_button:
					self.parent.has_button = True
				return
			else:	#invalid type
				raise TypeError("input type {} not recognized".format(repr(data_type)))

			self.get = func
			self._set = None

		def setter(self, func):
			'''Decorator to set setter. Setters should have the signature:
				(context:	the context supplied by the InputMux
				,value:		the new value after input)
			'''
			self._set = func
			return self

		def drawer(self, func):
			'''
			Decorator to set drawer. Drawers should have the signature:
				(mux:		the InputMux instance the _ListEl is a part of
				,value:		the value of the element obtained by the getter
				,coloring:	the row's Coloring object)
			'''
			self.draw = func
			return self

		def select(self):
			'''Open input overlay to modify value'''
			further_input = None
			if self._type == "color":
				further_input = ColorOverlay(self.parent.parent
					, self.get(self.parent.context))			#initial color
				@further_input.callback
				def callback(rgb):
					self._set(self.parent.context, rgb)
					return -1

			elif self._type == "str":
				further_input = InputOverlay(self.parent.parent
					, self.doc								#input window text
					, default=str(self.get(self.parent.context)))
				@further_input.callback
				def callback(string):
					self._set(self.parent.context, string)

			elif self._type == "enum":
				enumeration, index = self.get(self.parent.context)
				further_input = ListOverlay(self.parent.parent
					, enumeration)		#enum entries
				further_input.it = index

				@further_input.key_handler("tab")
				@further_input.key_handler("enter")
				@further_input.key_handler(' ')
				def callback(me):
					self._set(self.parent.context, me.it)
					return -1

			elif self._type == "bool":
				self._set(self.parent.context,
					not self.get(self.parent.context))	#toggle

			elif self._type == "button":
				ret = self._set(self.parent.context)
				self.parent.warn_exit = False
				return ret

			self.parent.warn_exit = self.parent.has_button
			if further_input:
				further_input.add()

		@staticmethod
		def draw_color(mux, value, coloring):
			'''Default color drawer'''
			coloring.add_indicator(' ', mux.parent.two56(value), 0)

		@staticmethod
		def draw_string(_, value, coloring):
			'''Default string drawer'''
			val = str(value)
			coloring.add_indicator(val, raw_num(7))	#yellow

		@classmethod
		def draw_enum(cls, mux, value, coloring):
			'''Default enum drawer'''
			#dereference and run string drawer
			cls.draw_string(mux, value[0][value[1]], coloring)

		@staticmethod
		def draw_bool(_, value, coloring):
			'''Default bool drawer'''
			coloring.add_indicator('y' if value else 'n'
				, raw_num(6) if value else raw_num(5))

	def listel(self, data_type):
		'''
		Frontend decorator to create a _ListEl. Abstracts away the need to
		supply `parent` and  transforms the decorator to be of the form
		@listel(data_type) (=> _ListEl(self, data_type, __decorated_func__))
		'''
		return staticize(self._ListEl, self, data_type)

	def try_warn(self, parent, overlay):
		'''Exit, warning about unconfirmed values'''
		if self.warn_exit:
			ConfirmOverlay(parent, "Really close menu? (y/n)"
				, overlay.remove).add()
			return None
		return -1
