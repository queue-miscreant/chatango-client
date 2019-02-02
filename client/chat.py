#!/usr/bin/env python3
#chat.py
'''
Overlays that provide chat room-like interfaces.
'''

import time
import asyncio
import traceback
from .display import SELECT_AND_MOVE, collen, numdrawing, raw_num \
	, Coloring, DisplayException
from .util import LazyIterList, History
from .base import staticize, quitlambda \
	, Box, OverlayBase, TextOverlay
from .overlay import ListOverlay, DisplayOverlay

CHAR_COMMAND = '`'

__all__ = ["CHAR_COMMAND", "CommandOverlay", "ChatOverlay", "add_message_scroller"]

class CommandOverlay(TextOverlay):
	'''Overlay to run commands'''
	replace = False
	history = History()	#global command history
	#command containers
	commands = {}
	_command_complete = {}

	def __init__(self, parent, caller=None):
		super().__init__(parent)
		self._sentinel = ord(CHAR_COMMAND)
		self.caller = caller
		self.text.setnonscroll(CHAR_COMMAND)
		self.text.completer.add_complete(CHAR_COMMAND, self.commands)
		for i, j in self._command_complete.items():
			self.text.add_command(i, j)
		self.control_history(self.history)
		self.add_keys({
			  'enter':			self._run
			, 'backspace':		self._wrap_backspace
			, "a-backspace":	quitlambda
		})

	def __call__(self, lines):
		lines[-1] = "COMMAND"

	def _on_sentinel(self):
		if self.caller:
			# override sentinel that added this overlay
			self.caller.text.append(CHAR_COMMAND)
		return -1

	def _wrap_backspace(self):
		'''Backspace a char, or quit out if there are no chars left'''
		if not str(self.text):
			return -1
		return self.text.backspace()

	def _run(self):
		'''Run command'''
		#parse arguments like a command line: quotes enclose single args
		args = self.escape_text(self.text)
		self.history.append(str(self.text))

		if args[0] not in self.commands:
			self.parent.blurb.push("command \"{}\" not found".format(args[0]))
			return -1
		self.parent.loop.create_task(self.run_command(
			  self.commands[args[0]] 
			, self.parent, args[1:], name=args[0]))
		return -1

	@staticmethod
	def escape_text(string):
		'''
		Formats a string with terminal-like arguments (separated by unescaped
		spaces) into a tuple
		'''
		text = ""
		args = []
		escaping = False
		single_flag = False
		double_flag = False
		for i in str(string):
			if escaping:
				escaping = False
				if not (single_flag or double_flag):
					text += i
					continue
				text += '\\'

			if i == '\\':
				escaping = True
			elif i == "'":
				single_flag ^= True
			elif i == '"':
				double_flag ^= True
			elif i == ' ' and not (single_flag or double_flag):
				args.append(text)
				text = ""
			else:
				text += i
		if escaping:
			text += "\\"
		args.append(text)
		return args

	@staticmethod
	async def run_command(command, param, args, name=""):
		try:
			if asyncio.iscoroutinefunction(command):
				result = await command(param, *args)
			else:
				result = command(param, *args)
			if isinstance(result, OverlayBase):
				result.add()
		except:
			param.blurb.push("an error occurred while running command %s" % \
				name)
			print(traceback.format_exc(), "\n")

	#decorators for containers
	@classmethod
	def command(cls, name, complete=None):
		'''
		Decorator that adds command `name` with argument suggestion `complete`
		`complete` may either be a list or a function returning a list and a
		number that specifies string index (of self.text) to start the
		suggestion from
		'''
		complete = complete if complete is not None else []
		def wrapper(func):
			cls.commands[name] = func
			if complete:
				cls._command_complete[name] = complete
			return func

		return wrapper

class EscapeOverlay(OverlayBase):
	'''Overlay for redirecting input after \\ is pressed'''
	replace = False
	def __init__(self, parent, scroll):
		super().__init__(parent)
		add_tab = staticize(self._add_char, scroll, '\t')
		add_newline = staticize(self._add_char, scroll, '\n')
		add_slash = staticize(self._add_char, scroll, '\\')

		self.add_keys({
			  -1:		quitlambda
			, 'tab':	add_tab
			, 'enter':	add_newline
			, 'n':		add_newline
			, '\\':		add_slash
			, 't':		add_tab
		})
		self.nomouse()
		self.noalt()

	@staticmethod
	def _add_char(scroll, char):
		scroll.append(char)
		return -1

class Messages:
	'''Container object for message objects'''
	INDENT = "    "
	def __init__(self, parent):
		self.parent = parent

		self.can_select = True
		self._all_messages = []	#contains every message as 4-lists of Coloring
								#objects, arg tuples, message length since last
								#break, and message ID
		self._lines = []		#contains every line currently or recently
								#involved in drawing
		self.msg_id = 0			#next message id
		#selectors
		self.selector = 0		#selected message
		self.start_height = 0	#to calculate which message we're drawing from
								#so that selected can be seen relative to it
		self.linesup = 0		#start drawing from this lines index (reversed)
		self.distance = 0		#number of lines down from start_height's message
		self.inner_height = 0	#inner message height, to start drawing message
								#lines late
		#lazy storage
		self.lazy_color	= [-1, -1] #latest/earliest messages to recolor
		self.lazy_filter = [-1, -1] #latest/earliest messages to refilter

		#deletion lambdas
		self.lazy_delete = []

	def clear(self):
		'''Clear all lines and messages'''
		self.can_select = True
		self._all_messages = []
		self._lines = []

		self.msg_id = 0
		self.selector = 0
		self.start_height = 0

		self.linesup = 0
		self.distance = 0
		self.inner_height = 0

		self.lazy_color	= [-1, -1]
		self.lazy_filter = [-1, -1]

		self.lazy_delete = []

	def stop_select(self):
		'''Stop selecting'''
		if self.selector:
			self.selector = 0
			self.linesup = 0
			self.inner_height = 0
			self.distance = 0
			self.start_height = 0
			#rebuild lines
			need_recolor = self.lazy_color[0] != -1
			if self.lazy_filter[0] != -1 or need_recolor:
				self.redo_lines(recolor=need_recolor)
			return 1
		return None

	def get_selected(self):
		'''
		Frontend for getting the selected message. Returns a 4-list:
		[0]: the message (in a coloring object); [1] an argument tuple, which
		is None for system messages; [2] the number of lines it occupies;
		[3]: its messageID
		returns None on not selecting
		'''
		if self.selector:
			return self._all_messages[-self.selector]
		return None

	def display(self, lines):
		if self.msg_id == 0:
			return
		#seperate traversals
		selftraverse, linetraverse = -self.linesup-1, -2
		lenself, lenlines = -len(self._lines), -len(lines)
		msgno = -self.start_height-1

		thismsg = self._all_messages[msgno][2] - self.inner_height
		#traverse list of lines
		while selftraverse >= lenself and linetraverse >= lenlines:
			reverse = SELECT_AND_MOVE if msgno == -self.selector else ""
			lines[linetraverse] = reverse + self._lines[selftraverse]

			selftraverse -= 1
			linetraverse -= 1
			thismsg -= 1
			while not thismsg:
				msgno -= 1
				if msgno >= -len(self._all_messages):
					thismsg = self._all_messages[msgno][2]
				else:
					break

	def apply_lazies(self, select, direction):
		'''
		Generator that yields on application of lazy iterators to mesages
		The value yielded corresponds to the kind of lazy operation performed
		0:	deletion
		1:	filtering
		2:	coloring
		'''
		message = self._all_messages[-select]
		#next message index is out of bounds
		next_oob = (select+direction < len(self._all_messages)) \
			and select+direction
		#next message if out of bounds to apply lazies on
		next_filter = self._all_messages[-select-direction][3] if next_oob else -1

		#test all lazy deleters
		for test, result in self.lazy_delete:
			if test(message, result):
				del self._all_messages[-select]
				if message[3] == self.lazy_filter[direction == 1]:
					self.lazy_filter[direction == 1] = next_filter
				if message[3] == self.lazy_color[direction == 1]:
					self.lazy_color[direction == 1] = next_filter
				return 0

		#lazy filters
		if message[3] == self.lazy_filter[direction == 1]:
			#use a dummy length (0/1) to signal that the message should be drawn
			message[2] = ((message[1] is None) or \
				not self.parent.filter_message(*message[1]))
			self.lazy_filter[direction == 1] = next_filter

		if message[3] == self.lazy_color[direction == 1]:
			#ignore system
			if message[1] is not None:
				message[0].clear()
				self.parent.colorize_message(message[0], *message[1])
			self.lazy_color[direction == 1] = next_filter

		return message[2]

	def up(self):
		height = self.parent.height-1
		#scroll within a message if possible, and exit
		if self.selector \
		and self._all_messages[-self.selector][2] - height > self.inner_height:
			self.linesup += 1
			self.inner_height += 1
			return -1

		select = self.selector+1
		addlines = 0
		while not addlines:
			if select > len(self._all_messages):
				return 0
			addlines = self.apply_lazies(select, 1)
			select += 1

		#if the message just had its length calculated as 1, this barely works
		offscreen = (self.distance + addlines - height)
		#next message out of bounds and select refers to an actual message
		if self.linesup + self.distance + addlines > len(self._lines) \
		and select-1 <= len(self._all_messages):
			message = self._all_messages[-select+1]
			#break the message, then add at the beginning
			new = message[0].breaklines(self.parent.width, self.INDENT)
			message[2] = len(new)
			#append or prepend
			self._lines[0:0] = new
			offscreen += message[2]-addlines
			addlines = message[2]

		self.distance += addlines

		#can only make sense when the instance properly handles variables
		#so checking validity is futile
		if offscreen > 0:
			#get a delta from the top, just in case we aren't there already
			self.linesup += offscreen
			canscroll = self._all_messages[-self.start_height-1][2] - self.inner_height
			#scroll through messages if needed
			if offscreen - canscroll >= 0:
				while offscreen - canscroll >= 0:
					offscreen -= canscroll
					self.start_height += 1
					canscroll = self._all_messages[-self.start_height-1][2]
				self.inner_height = offscreen
			else:
				self.inner_height += offscreen

			self.distance = height

		self.selector = select-1

		return addlines

	def down(self):
		if not self.selector:
			return 0
		height = self.parent.height-1
		#scroll within a message if possible, and exit
		if self.selector == self.start_height+1 \
		and self.inner_height > 0:	#there is at least one hidden line
			self.linesup -= 1
			self.inner_height -= 1
			return -1

		select = self.selector-1
		addlines = 0
		while not addlines and select > 0:
			addlines = self.apply_lazies(select, -1)
			select -= 1
		select += (addlines > 0)

		last_lines = self._all_messages[-self.selector][2]
		next_pos = self.linesup + self.distance - last_lines - addlines
		#append message lines if necessary
		if next_pos < 0 < select:
			message = self._all_messages[-select]
			#break the message, then add at the end
			new = message[0].breaklines(self.parent.width, self.INDENT)
			addlines = len(new)
			message[2] = addlines
			self._lines.extend(new)
			#to cancel out with distance in the else statement below
			self.inner_height = -max(addlines, addlines-height)

		#fix the last line to show all of the message
		if select == self.start_height+1:
			self.distance = min(height, addlines)
			newheight = max(0, addlines - height)
			#this newheight will hide fewer lines; it's less than inner_height
			#the delta, if there are still lines left
			self.linesup -= self.inner_height - newheight
			self.inner_height = newheight
			#start_height is off by one
			self.start_height = select-1
		#scroll down to the next message
		elif select and self.selector == self.start_height+1:
			self.distance = min(height, addlines)
			self.linesup -= min(height, self.inner_height + self.distance)

			self.inner_height = max(0, addlines - height)
			self.start_height = select-1
		else:
			self.distance -= last_lines

		self.selector = select
		if not self.selector:
			self.distance = 0
			self.linesup = 0
			self.start_height = 0
			self.inner_height = 0

		return addlines

	def append(self, message, args=None):
		'''Add new message to the end of _all_messages and lines'''
		#undisplayed messages have length zero
		msg = [message, args, 0, self.msg_id]
		self.msg_id += 1
		self._all_messages.append(msg)

		#don't bother drawing; filter
		if (args is not None) and self.parent.filter_message(*args):
			self.selector += (self.selector > 0)
			self.start_height += (self.start_height > 0)
			return msg[-1]

		new = message.breaklines(self.parent.width, self.INDENT)
		msg[2] = len(new)
		#adjust selector iterators
		if self.selector:
			self.selector += 1
			#scrolled up too far to see
			if self.start_height \
			or msg[2] + self.distance > (self.parent.height-1):
				self.start_height += 1
				self.lazy_filter[0]	= msg[3]
				self.lazy_color[0]	= msg[3]
				return msg[-1]
			self.distance += msg[2]
		#add lines if and only if necessary
		self._lines.extend(new)

		return msg[-1]

	def prepend(self, message, args=None):
		'''Prepend new message. Use msg_prepend instead'''
		#run filters early so that the message can be selected up to properly
		dummy = not self.parent.filter_message(*args) if args is not None else 1
		msg = [message, args, dummy, self.msg_id]
		self.msg_id += 1
		self._all_messages.insert(0, msg)
		#lazyfilter checking ensures that prepending to lines is valid
		if dummy and self.lazy_filter[1] == -1:
			new = message.breaklines(self.parent.width, self.INDENT)
			self._lines[0:0] = new
			msg[2] = len(new)

		return msg[-1]

	def delete(self, result, test=lambda x, y: x[3] == y):
		'''Delete message from value result and callable test'''
		if not callable(test):
			raise TypeError("delete requires callable")

		msgno = self.start_height+1
		height = self._all_messages[-msgno][2]-self.inner_height

		while height <= self.parent.height-1:
			if test(self._all_messages[-msgno], result):
				del self._all_messages[-msgno]
				self.redo_lines()
				return
			msgno += 1
			height += self._all_messages[-msgno][2]

		self.lazy_delete.append(test, result)

	def from_position(self, x, y):
		'''Get the message and depth into the message at position x,y'''
		#we always draw "upward," so 0 being the bottom is more useful
		y = (self.parent.height-1) - y
		if y <= 0:
			return "", -1
		#we start drawing from this message
		msgno = self.start_height+1
		msg = self._all_messages[-msgno]
		#visible lines shown
		height = msg[2] - self.inner_height
		#find message until we exceed the height
		while height < y:
			#advance the message number, or return if we go too far
			msgno += 1
			if msgno > len(self._all_messages):
				return "", -1
			msg = self._all_messages[-msgno]
			height += msg[2]

		#line depth into the message
		depth = height - y
		pos = 0
		#adjust the position
		for i in range(depth):
			#only subtract from the length of the previous line if it's not the first one
			pos += numdrawing(self._lines[i-height]) - (i and len(self.INDENT))
		if x >= collen(self.INDENT) or not depth:
			#try to get a slice up to the position 'x'
			pos += max(0
				, numdrawing(self._lines[depth-height], x) - len(self.INDENT))
		return msg, pos

	def scroll_to(self, index):
		'''
		Directly set selector and start_height, then redo_lines.
		Redraw necessary afterward.
		'''
		if not self._all_messages:
			return
		start = index
		i = self._all_messages[-start]
		while start < len(self._all_messages) and not i[2]:
			start += 1
			i = self._all_messages[-start]

		#try again going downwards if we need to (the last message is blank)
		if start == len(self._all_messages) and not i[2]:
			start = index-1
			i = self._all_messages[-start]
			while start > 1 and not i[2]:
				start -= 1
				i = self._all_messages[-start]

		self.selector = start
		self.start_height = index-1
		self.redo_lines()

	def scroll_top(self):
		top = self.selector
		self.scroll_to(len(self._all_messages))
		if self.selector == top:
			return -1
		return None

	def iterate_with(self, callback):
		'''
		Returns an iterator that yields when the callback is true.
		Callback is called with arguments passed into append (or msg_append...)
		'''
		select = 1
		while select <= len(self._all_messages):
			message = self._all_messages[-select]
			#ignore system messages
			if message[1] and callback(*message[1]):
				yield message[0], select
			select += 1

	#REAPPLY METHODS-----------------------------------------------------------
	def redo_lines(self, width=None, height=None, recolor=False):
		'''
		Redo lines, if current lines does not represent the unfiltered messages
		or if the width has changed
		'''
		if not self._all_messages:
			return
		#search for a fitting message to set as selector
		start = self.selector or 1
		i = self._all_messages[-start]
		while start < len(self._all_messages) and (i[1] is not None) \
		and self.parent.filter_message(*i[1]):
			start += 1
			i = self._all_messages[-start]
		#only need if we were selecting to begin with
		self.selector = self.selector and start

		#a new start height must be decided
		if width or height or self.selector:
			self.start_height = max(0, self.selector-1)
		width = width if width is not None else self.parent.width
		height = height if height is not None else self.parent.height
		#must change lazy_color bounds
		if self.start_height:
			recolor = True

		#don't decolor system messages
		if recolor and i[1] is not None:
			i[0].clear()
			self.parent.colorize_message(i[0], *i[1])
		newlines = i[0].breaklines(width, self.INDENT)
		#guaranteed to be an actual line by above loop
		i[2] = len(newlines)

		self.inner_height = max(0, i[2] - height)
		#distance only if we're still selecting
		self.distance = min(height, self.selector and i[2])
		self._linesup = self.inner_height

		msgno, lineno = start+1, self.distance

		self.lazy_filter[0]	= self._all_messages[-max(0, start-1)][3] \
			if self.selector else -1

		while lineno < height and msgno <= len(self._all_messages):
			i = self._all_messages[-msgno]
			system = i[1] is None
			#check if the message should be drawn
			if recolor and not system:	#don't decolor system messages
				i[0].clear()
				self.parent.colorize_message(i[0], *i[1])
			#re-filter message
			if not system and self.parent.filter_message(*i[1]):
				i[2] = 0
				msgno += 1
				continue
			#break and add lines
			new = i[0].breaklines(width, self.INDENT)
			newlines[0:0] = new
			i[2] = len(new)
			lineno += i[2]
			msgno += 1

		self.lazy_filter[1]	= self._all_messages[-msgno][3] \
			if msgno-1 != len(self._all_messages) else -1

		if recolor:
			#duplicate the lazy bounds
			self.lazy_color = list(self.lazy_filter)

		self._lines = newlines
		self.can_select = True

	def recolor_lines(self):
		'''Re-apply parent's colorize_message and redraw all visible lines'''
		if not self._all_messages:
			return
		width = self.parent.width
		height = self.parent.height-1

		start = self.start_height+1
		while self._all_messages[-start][2] == 0 \
		and start <= len(self._all_messages):
			#find a non-hidden message
			start += 1
		start_message = self._all_messages[-start]

		if start_message[1] is not None:	#don't decolor system messages
			start_message[0].clear()
			self.parent.colorize_message(start_message[0], *start_message[1])

		newlines = start_message[0].breaklines(width, self.INDENT)
		if len(newlines) != start_message[2]:
			raise DisplayException("recolor_lines called before redo_lines")

		self.lazy_color[0] = self._all_messages[-self.start_height][3] \
			if self.start_height else -1

		lineno, msgno = start_message[2]-self.inner_height, start+1
		while lineno < height and msgno <= len(self._all_messages):
			message, args, length, _ = self._all_messages[-msgno]
			if args is not None:	#don't decolor system messages
				message.clear()
				self.parent.colorize_message(message, *args)
			if length: #unfiltered (non zero lines)
				new = message.breaklines(width, self.INDENT)
				if len(new) != length:
					raise DisplayException("recolor_lines called before redo_lines")
				newlines[0:0] = new
				lineno += length
			msgno += 1

		self.lazy_color[1] = self._all_messages[-msgno][3] \
			if msgno-1 != len(self._all_messages) else -1

		self._lines = newlines
		self.linesup = self.inner_height

class ChatOverlay(TextOverlay):
	'''
	Overlay that can push and select messages, and has an input box.
	Optionally pushes time messages every `push_times` seconds. 0 to disable.
	'''
	replace = True
	_monitors = {}
	def __init__(self, parent, push_times=600):
		super().__init__(parent)
		self._sentinel = ord(CHAR_COMMAND)
		self._push_times = push_times
		self._push_task = None
		self._last_time = -1

		self.messages = Messages(self)
		self.history = History()
		self.control_history(self.history)

		self.add_keys({
			  '\\':		self._replace_back
			, 'a-k':	self.select_up
			, 'a-j':	self.select_down
			, "mouse-wheel-up":		self.select_up
			, "mouse-wheel-down":	self.select_down
		})

		examiners = self._monitors.get(type(self).__name__)
		if examiners is not None:
			self._examine = examiners
		else:
			self._examine = []

	@property
	def can_select(self):
		return self.messages.can_select

	@can_select.setter
	def can_select(self, new):
		self.messages.can_select = new

	async def _time_loop(self):
		'''Prints the current time every 10 minutes'''
		while self._push_times:
			await asyncio.sleep(self._push_times)
			self.msg_time()

	#method overloading---------------------------------------------------------
	def __call__(self, lines):
		'''Display messages'''
		self.messages.display(lines)
		lines[-1] = Box.CHAR_HSPACE * self.parent.width

	def _on_sentinel(self):
		'''Input some text, or enter CommandOverlay when CHAR_CURSOR typed'''
		CommandOverlay(self.parent, self).add()

	def _post(self):
		if self.messages.stop_select():
			self.parent.update_input()
			return 1
		return None

	def add(self):
		'''Start timeloop and add overlay'''
		super().add()
		self.messages.redo_lines()
		if self._push_times > 0:
			self._push_task = self.parent.loop.create_task(self._time_loop())

	def remove(self):
		'''
		Quit timeloop (if it hasn't already exited).
		Exit client if last overlay.
		'''
		if self._push_times:
			#finish running the task
			self._push_times = 0
			self._push_task.cancel()
		if self.index == 0:
			self.parent.stop()
		super().remove()

	def resize(self, newx, newy):
		'''Resize scrollable and maybe draw lines again if width changed'''
		super().resize(newx, newy)
		self.messages.redo_lines(newx, newy)

	#VIRTUAL FILTERING------------------------------------------
	@classmethod
	def examine(cls, class_name):
		'''
		Wrapper for a function that monitors messages. Such function may perform some
		effect such as pushing a new message or alerting the user
		'''
		def wrap(func):
			if cls._monitors.get(class_name) is None:
				cls._monitors[class_name] = []
			cls._monitors[class_name].append(func)
		return wrap

	def colorize_message(self, msg, *args):
		'''
		Virtual function. Overload to apply some transformation on argument
		`msg`, which is a client.Coloring object. Arguments are left generic
		so that the user can define message args
		'''
		return msg

	def filter_message(self, *args):
		'''
		Virtual function called to see if a message can be displayed. If False,
		the message can be displayed. Otherwise, the message is pushed to
		_all_messages without drawing to lines. Arguments are left generic so
		that the user can define message args
		'''
		return False

	def _replace_back(self, *_):
		'''
		Add a newline if the next character is n,
		or a tab if the next character is t
		'''
		EscapeOverlay(self.parent, self.text).add()

	#MESSAGE SELECTION----------------------------------------------------------
	def _max_select(self):
		self.parent.sound_bell()
		self.can_select = 0

	def select_up(self):
		'''Select message up'''
		if not self.can_select:
			return 1
		#go up the number of lines of the "next" selected message
		upmsg = self.messages.up()
		#but only if there is a next message
		if not upmsg:
			self._max_select()
		return 1

	def select_down(self):
		'''Select message down'''
		if not self.can_select:
			return 1
		#go down the number of lines of the currently selected message
		self.messages.down()
		if not self.messages.selector:
			#move the cursor back
			self.parent.update_input()
		return 1

	def select_top(self):
		'''Select top message'''
		if not self.can_select:
			return 1
		if self.messages.scroll_top() == -1:
			self._max_select()
		return 1

	def clear(self):
		'''Clear all lines and messages'''
		self.can_select = True
		self.messages.clear()

	def redo_lines(self, recolor=False):
		self.messages.redo_lines(recolor=recolor)
		self.parent.schedule_display()

	def recolor_lines(self):
		self.messages.recolor_lines()
		self.parent.schedule_display()

	#MESSAGE ADDITION----------------------------------------------------------
	def msg_system(self, base):
		'''System message'''
		base = Coloring(base)
		base.insert_color(0, raw_num(1))
		self.parent.schedule_display()
		return self.messages.append(base, None)

	def msg_time(self, numtime=None, predicate=""):
		'''Push a system message of the time'''
		dtime = time.strftime("%H:%M:%S"
			, time.localtime(numtime or time.time()))
		ret = self.msg_system(predicate+dtime)
		if not predicate:
			if self._last_time == ret-1:
				self.messages.delete(self._last_time)
			self._last_time = ret
		return ret

	def msg_append(self, post, *args):
		'''Parse a message, apply colorize_message, and append'''
		post = Coloring(post)
		self.colorize_message(post, *args)
		for i in self._examine:
			i(self, post, *args)
		self.parent.schedule_display()
		return self.messages.append(post, list(args))

	def msg_prepend(self, post, *args):
		'''Parse a message, apply colorize_message, and prepend'''
		post = Coloring(post)
		self.colorize_message(post, *args)
		self.parent.schedule_display()
		return self.messages.prepend(post, list(args))

class _MessageScrollOverlay(DisplayOverlay):
	'''
	DisplayOverlay with the added capabilities to display messages in a
	LazyIterList and to scroll a ChatOverlay to the message index of such
	a message. Do not directly create these; use add_message_scroller.
	'''
	def __init__(self, overlay, lazy_list, early, late):
		self.lazy_list = lazy_list

		self.msgno = lazy_list[0][1]
		self.early = early
		self.late = late

		super().__init__(overlay.parent, lazy_list[0][0]
			, overlay.messages.INDENT)

		scroll_down, scroll_up, scroll_to = \
			  lambda: self.next(-1) \
			, lambda: self.next(1) \
			, lambda: overlay.messages.scroll_to(self.msgno) or -1

		self.add_keys({
			  'tab':	scroll_to
			, 'enter':	scroll_to
			, 'N':		scroll_down
			, 'n':		scroll_up
			, 'a-j':	scroll_down
			, 'a-k':	scroll_up
		})

	def next(self, step):
		attempt = self.lazy_list.step(step)
		if attempt:
			self.change_display(attempt[0])
			self.msgno = attempt[1]
		elif step == 1:
			self.parent.blurb.push(self.early)
		elif step == -1:
			self.parent.blurb.push(self.late)

def add_message_scroller(overlay, callback, empty, early, late):
	'''
	Add a message scroller for a particular callback.
	This wraps Messages.iterate_with with a LazyIterList, spawns an instance of
	_MessageScrollOverlay, and adds it to the same parent as overlay.
	Error blurbs are printed to overlay's parent: `empty` for an exhausted
	iterator, `early` for when no earlier messages matching the callback are
	found, and `late` for the same situation with later messages.
	'''
	try:
		lazy_list = LazyIterList(overlay.messages.iterate_with(callback))
	except TypeError:
		return overlay.parent.blurb.push(empty)

	ret = _MessageScrollOverlay(overlay, lazy_list, early, late)
	ret.add()
	return ret

@CommandOverlay.command("help")
def list_commands(parent, *_):
	'''Display a list of the defined commands and their docstrings'''
	command_list = ListOverlay(parent, list(CommandOverlay.commands))

	@command_list.key_handler("enter")
	def select(self):
		new = CommandOverlay(parent)
		new.text.append(self.list[self.it])
		self.swap(new)

	return command_list

@CommandOverlay.command("q")
def close(parent, *_):
	parent.stop()
