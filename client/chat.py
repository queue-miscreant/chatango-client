#!/usr/bin/env python3
#client/chat.py
'''Overlays that provide chatroom-like interfaces.'''
import time
import asyncio
import traceback
from collections import deque

from .display import SELECT_AND_MOVE, collen, numdrawing, colors, Coloring
from .util import LazyIterList, History
from .base import staticize, quitlambda, key_handler \
	, Box, KeyException, KeyContainer, OverlayBase, TextOverlay
from .input import ListOverlay, DisplayOverlay
__all__ = ["CommandOverlay", "ChatOverlay", "add_message_scroller"]

class CommandOverlay(TextOverlay):
	'''Overlay to run commands'''
	CHAR_COMMAND = '/'
	replace = False
	history = History()	#global command history
	#command containers
	commands = {}
	_command_complete = {}

	def __init__(self, parent, caller=None):
		super().__init__(parent)
		self._sentinel = ord(self.CHAR_COMMAND)
		self.caller = caller
		self.text.setnonscroll(self.CHAR_COMMAND)
		self.text.completer.add_complete(self.CHAR_COMMAND, self.commands)
		for i, j in self._command_complete.items():
			self.text.add_command(i, j)
		self.control_history(self.history)

	def __call__(self, lines):
		lines[-1] = "COMMAND"

	def _on_sentinel(self):
		if self.caller is not None:
			# override sentinel that added this overlay
			self.caller.text.append(self.CHAR_COMMAND)
		return -1

	@key_handler("backspace")
	def _wrap_backspace(self):
		'''Backspace a char, or quit out if there are no chars left'''
		if not str(self.text):
			return -1
		return self.text.backspace()

	@key_handler("enter")
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
			result = command(param, *args)
			if asyncio.iscoroutine(result):
				result = await result
			if isinstance(result, OverlayBase):
				result.add()
		except Exception as exc: #pylint: disable=broad-except
			param.blurb.push("%s occurred in command '%s'" % (exc, name))
			traceback.print_exc()

	@classmethod
	def command(cls, name, complete=None):
		'''
		Decorator that adds command `name` with argument suggestion `complete`,
		which may either be a list or a callable with signature (index), the
		string index to start completion from, that returns a list
		'''
		complete = complete if complete is not None else []
		def wrapper(func):
			cls.commands[name] = func
			if complete:
				cls._command_complete[name] = complete
			return func

		return wrapper

class Message(Coloring):
	'''
	Virtual wrapper class around "Coloring" objects. Allows certain kinds of
	message objects (like those from a certain service) to have a standard
	colorizing method, without binding tightly to a ChatOverlay subclass
	'''
	INDENT = "    "
	SHOW_CLASS = True
	msg_count = 0
	def __init__(self, msg, remove_fractur=True, **kwargs):
		super().__init__(msg, remove_fractur)
		self.__dict__.update(kwargs)
		if hasattr(self, "_examine"):
			for examiner in self._examine:
				examiner(self)

		self._mid = Message.msg_count
		#memoization
		self._cached_display = []
		self._cached_hash = -1	#hash of coloring
		self._cached_width = 0	#screen width
		self._last_recolor = -1
		Message.msg_count += 1

	mid = property(lambda self: self._mid)
	filtered = property(lambda self: self.SHOW_CLASS and self.filter())
	display = property(lambda self: self._cached_display)
	height = property(lambda self: len(self._cached_display))

	def colorize(self):
		'''
		Virtual method to standardize colorizing a particular subclass of
		message. Used in Messages objects to create a contiguous display of
		messages.
		'''

	def filter(self): #pylint: disable=no-self-use
		'''
		Virtual method to standardize filtering of a particular subclass of
		message. Used in Messages objects to decide whether or not to display a
		message. True means that the message is filtered.
		'''
		return False

	def cache_display(self, width, recolor_count):
		'''
		Break a message to `width` columns. Does nothing if matches last call.
		'''
		if self.filtered: #invalidate cache
			self._cached_display.clear()
			self._last_recolor = -1
			self._cached_hash = -1
			self._cached_width = 0
			return
		self_hash = self._cached_hash
		if self._last_recolor < recolor_count:
			#recolor message in the same way
			self.clear()
			self.colorize()
			self._last_recolor = recolor_count
			self_hash = hash(self)
		if self._cached_hash == self_hash and self._cached_width == width: #don't break lines again
			return
		self._cached_display = super().breaklines(width, self.INDENT)
		self._cached_hash = self_hash
		self._cached_width = width

	def dump(self, prefix, coloring=False):
		'''Dump public variables associated with the message'''
		publics = {i: j for i, j in self.__dict__.items() \
			if not i.startswith('_')}
		if coloring:
			print(repr(self), prefix, publics)
		else:
			print(prefix, publics)

	@classmethod
	def examine(cls, func):
		'''
		Wrapper for a function that monitors instantiation of messages.
		`func` must have signature (message), the instance in question
		'''
		if not hasattr(cls, "_examine"):
			cls._examine = []
		cls._examine.append(func)
		return func

	@classmethod
	def key_handler(cls, key_name, override_val=None):
		'''
		Decorator for adding a key handler. Key handlers for Messages objects
		expect signature (message, calling overlay)
		Mouse handlers expect signature (message, calling overlay, position)
		See OverlayBase.add_keys documentation for valid values of `key_name`
		'''
		if not hasattr(cls, "keys"):
			cls.keys = KeyContainer()
			#mouse callbacks don't work quite the same; they need an overlay
			cls.keys.nomouse()
		def ret(func):
			cls.keys.add_key(key_name, func, return_val=override_val)
			return func
		return ret

class SystemMessage(Message):
	'''System messages that are colored red-on-white'''
	def colorize(self):
		self.insert_color(0, colors.system)

class Messages: #pylint: disable=too-many-instance-attributes
	'''Container object for Message objects'''
	def __init__(self, parent):
		self.parent = parent

		self.can_select = True
		self._all_messages = deque()	#all Message objects
		#selectors
		self._selector = 0		#selected message
		self._start_message = 0	#start drawing upward from this index+1
		self._start_inner = 0	#ignore drawing this many lines in start_message
		self._height_up = 0		#lines between start_message and the selector
		#lazy storage
		self._lazy_bounds = [0, 0]	#latest/earliest messages to recolor
		self._lazy_offset = 0		#lines added since last lazy_bounds modification
		self._last_recolor = 0

	def clear(self):
		'''Clear all lines and messages'''
		self.can_select = True
		self._all_messages.clear()
		self._selector = 0
		self._start_message = 0
		self._start_inner = 0
		self._height_up = 0
		self._lazy_bounds = [0, 0]
		self._lazy_offset = 0
		self._last_recolor += 1

	def stop_select(self):
		'''Stop selecting'''
		if self._selector:
			#only change the lazy bounds if our range isn't a continuous run
			if self._start_message - self._lazy_offset \
			 not in range(*self._lazy_bounds):
				self._lazy_bounds = [0, 0]
			self.can_select = True
			self._selector = 0
			self._start_message = 0
			self._start_inner = 0
			self._height_up = 0
			self._lazy_offset = 0
			return True
		return False

	@property
	def selected(self):
		'''
		Frontend for getting the selected message. Returns None if no message is
		selected, or a Message object (or subclass)
		'''
		return self._all_messages[-self._selector] if self._selector else None

	@property
	def has_hidden(self):
		'''Retrieve whether there are hidden messages (have scrolled upward)'''
		return bool(self._start_message)

	def display(self, lines):
		'''Using cached data in the messages, display to lines'''
		if not self._all_messages:
			return
		line_number = 2
		msg_number = self._start_message + 1
		ignore = self._start_inner
		cached_range = range(*self._lazy_bounds)
		self._lazy_bounds[0] = min(self._lazy_bounds[0] + self._lazy_offset, msg_number)
		#traverse list of lines
		while line_number <= len(lines) and msg_number <= len(self._all_messages):
			reverse = SELECT_AND_MOVE if msg_number == self._selector else ""
			msg = self._all_messages[-msg_number]
			if msg_number - self._lazy_offset not in cached_range:
				msg.cache_display(self.parent.width, self._last_recolor)
			#if a message is ignored, then msg.display is []
			for line_count, line in enumerate(reversed(msg.display)):
				if ignore > line_count:
					continue
				if line_number > len(lines):
					break
				ignore = 0
				lines[-line_number] = reverse + line
				line_number += 1
			msg_number += 1
		self._lazy_bounds[1] = max(self._lazy_bounds[1] + self._lazy_offset, msg_number)
		self._lazy_offset = 0

	def up(self, amount=1):
		height = self.parent.height-1

		#the currently selected message is the top message
		if self._start_message+1 == self._selector:
			new_inner = min(self._start_inner + amount	#add to the inner height
				, self.selected.height - height)		#or use the max possible
			if new_inner >= 0:
				inner_diff = new_inner - self._start_inner
				self._start_inner = new_inner
				amount -= inner_diff
				if amount <= 0:
					return inner_diff

		#out of checking for scrolling inside of a message; go by messages now
		select = self._selector+1
		addlines = 0
		cached_range = range(*self._lazy_bounds)
		while select - self._selector <= amount:
			if select > len(self._all_messages):
				break
			if select - self._lazy_offset not in cached_range:
				#recache to get the correct message height
				self._all_messages[-select].cache_display(self.parent.width, self._last_recolor)
			addlines += self._all_messages[-select].height
			select += 1
		self._lazy_bounds[1] = max(self._lazy_bounds[1] + self._lazy_offset, select)
		self._lazy_offset = 0
		self._selector = select-1

		#so at this point we're moving up `addlines` lines
		self._height_up += addlines
		if self._height_up > height:
			start = self._start_message+1
			addlines = self._height_up - height
			startlines = -self._start_inner
			last_height = 0
			while startlines <= addlines:
				last_height = self._all_messages[-start].height
				startlines += last_height
				start += 1
			self._start_message = start-2
			#the last message is perfect for what we need
			if startlines - last_height == addlines:
				self._start_inner = 0
			#the first message we checked was enough
			elif startlines == last_height:
				self._start_inner = addlines
			else:
				self._start_inner = last_height - startlines + addlines

			self._height_up = height

		return addlines

	def down(self, amount=1):
		if not self._selector:
			return 0
		height = self.parent.height-1
		#scroll within a message if possible, if there is a hidden line
		if self._selector == self._start_message+1 and self._start_inner > 0:
			new_inner = max(0, self._start_inner - amount)
			inner_diff = self._start_inner - new_inner
			self._start_inner = new_inner
			amount -= new_inner
			if new_inner == 0:
				if self._selector == 1:
					self.stop_select()
					return 0
				return inner_diff

		#out of checking for scrolling inside of a message; go by messages now
		select = self._selector
		last_height = 0
		addlines = 0
		cached_range = range(*self._lazy_bounds)
		while self._selector - select <= amount:
			#stop selecting if too low
			if select == 0:
				self.stop_select()
				return 0
			if select - self._lazy_offset not in cached_range:
				self._all_messages[-select].cache_display(self.parent.width, self._last_recolor)
			last_height = self._all_messages[-select].height
			addlines += last_height
			select -= 1

		self._lazy_bounds[0] = min(self._lazy_bounds[0] + self._lazy_offset, select+1)
		self._lazy_offset = 0
		self._selector = select+1

		#so at this point we're moving down `addlines` lines
		self._height_up -= addlines - last_height
		if self._height_up < last_height:
			self._start_message = self._selector-1
			self._start_inner = max(self.selected.height - height, 0)
			self._height_up = min(self.selected.height, height)

		return addlines

	def append(self, msg: Message):
		'''Add new message to the left (bottom)'''
		#undisplayed messages have length zero
		self._all_messages.append(msg)
		msg.cache_display(self.parent.width, self._last_recolor)

		#adjust selector iterators
		if self._selector:
			self._selector += 1
			#scrolled up too far to see
			if self._start_message == 0 \
			and msg.height + self._height_up <= (self.parent.height-1):
				self._height_up += msg.height
				self._lazy_offset += 1
				return msg.mid
			self._start_message += 1

		return msg.mid

	def prepend(self, msg: Message):
		'''Prepend new message. Use msg_prepend instead'''
		self._all_messages.appendleft(msg)
		msg.cache_display(self.parent.width, self._last_recolor)
		return msg.mid

	def delete(self, result, test=lambda x, y: x.mid == y):
		''' Delete a message if `test`(a contained Message, `result`) is True'''
		if not callable(test):
			raise TypeError("delete requires callable")

		start = self._start_message+1
		#height remaining
		start_height = -self._start_inner

		while start_height <= self.parent.height-1:
			msg = self._all_messages[-start]
			if test(msg, result):
				del self._all_messages[-start]
				if self._selector > start: #below the selector
					self._selector += 1
					self._height_up -= msg.height
					#have to add back the inner height
					if start == self._selector:
						self._height_up += self._start_inner
						if self._selector == self._start_inner: #off by 1 anyway
							self._start_inner += 1
							self._height_up = self.selected.height
				return
			start_height += msg.height
			start += 1

	def from_position(self, x, y):
		'''Get the message and depth into the message at position x,y'''
		#we always draw "upward," so 0 being the bottom is more useful
		y = (self.parent.height-1) - y
		if y <= 0:
			return "", -1
		#we start drawing from this message
		start = self._start_message+1
		height = -self._start_inner
		#find message until we exceed the height
		while height < y:
			#advance the message number, or return if we go too far
			if start > len(self._all_messages):
				return "", -1
			msg = self._all_messages[-start]
			height += msg.height
			start += 1

		#line depth into the message
		depth = height - y
		indent_size = numdrawing(msg.INDENT)
		#only ignore the indent on messages larger than 0
		pos = sum(numdrawing(line) - (i and indent_size) \
			for i, line in enumerate(msg.display[:depth]))

		indent_size = indent_size if depth else 0
		if x >= collen(msg.INDENT) or not depth:
			#try to get a slice up to the position 'x'
			pos += min(len(str(msg))-1, \
				max(0, numdrawing(msg.display[depth], x) - indent_size))
		return msg, pos

	def scroll_to(self, index):
		'''
		Directly set selector and start_height, then redo_lines.
		Redraw necessary afterward.
		'''
		if not self._all_messages:
			return
		height = self.parent.height-1

		self._selector = index
		self._start_message = index-1
		if index:
			self._start_inner = max(self.selected.height - height, 0)
			self._height_up = min(self.selected.height, height)
		self._lazy_bounds = [index, index]
		self._lazy_offset = 0

	def scroll_top(self):
		top = self._selector
		self.scroll_to(len(self._all_messages))
		if self._selector == top:
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
			try:
				ret = callback(message)
			except Exception: #pylint: disable=broad-except
				traceback.print_exc()
				continue
			if ret:
				yield message, select
			select += 1

	#REAPPLY METHODS-----------------------------------------------------------
	def redo_lines(self, recolor=True):
		'''Re-apply Message coloring and redraw all visible lines'''
		if recolor:
			self._last_recolor += 1
		self._lazy_bounds = [self._start_message, self._start_message]

class ChatOverlay(TextOverlay):
	'''
	Overlay that can push and select messages, and has an input box.
	Optionally pushes time messages every `push_times` seconds, 0 to disable.
	'''
	replace = True
	def __init__(self, parent, push_times=600):
		super().__init__(parent)
		self._sentinel = ord(CommandOverlay.CHAR_COMMAND)
		self._push_times = push_times
		self._push_task = None
		self._last_time = -1

		self.messages = Messages(self)
		self.history = History()
		self.control_history(self.history)

	can_select = property(lambda self: self.messages.can_select)
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
		separator = Box.CHAR_HSPACE * (self.parent.width - 1)
		separator += '^' if self.messages.has_hidden else Box.CHAR_HSPACE
		lines[-1] = separator

	def _on_sentinel(self):
		'''Enter CommandOverlay when CHAR_CURSOR typed'''
		CommandOverlay(self.parent, self).add()

	def add(self):
		'''Start timeloop and add overlay'''
		super().add()
		#self.messages.redo_lines()
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
		self.messages.redo_lines(False)
		return 1

	def run_key(self, chars):
		'''Delegate running characters to a selected message that supports it'''
		selected = self.messages.selected
		ret = None
		try:
			if selected is not None and hasattr(selected, "keys"):
				#pass in the message and this overlay to the handler
				ret = selected.keys(chars, selected, self)
			else:
				raise KeyException
		except KeyException:
			ret = self.keys(chars, self)

		#stop selecting if False is returned
		if not ret and self.messages.stop_select():
			self.parent.update_input()
			ret = 1
		elif ret == -1:
			self.remove()
		return ret

	@key_handler("mouse")
	def _mouse(self, state, x, y):
		'''Delegate mouse to message clicked on'''
		msg, pos = self.messages.from_position(x, y)
		if hasattr(msg, "keys"):
			return msg.keys.mouse(msg, self, pos, state=state, x=x, y=y)
		return 1

	#MESSAGE SELECTION----------------------------------------------------------
	def _max_select(self):
		self.parent.sound_bell()
		self.can_select = 0

	@key_handler("ppage", amount=5)
	@key_handler("a-k")
	@key_handler("mouse-wheel-up")
	def select_up(self, amount=1):
		'''Select message up'''
		if not self.can_select:
			return 1
		#go up the number of lines of the "next" selected message
		upmsg = self.messages.up(amount)
		#but only if there is a next message
		if not upmsg:
			self._max_select()
		return 1

	@key_handler("npage", amount=5)
	@key_handler("a-j")
	@key_handler("mouse-wheel-down")
	def select_down(self, amount=1):
		'''Select message down'''
		if not self.can_select:
			return 1
		#go down the number of lines of the currently selected message
		self.messages.down(amount)
		if self.messages.selected is None:
			#move the cursor back
			self.parent.update_input()
		return 1

	@key_handler("a-g")
	def select_top(self):
		'''Select top message'''
		if not self.can_select:
			return 1
		if self.messages.scroll_top() == -1:
			self._max_select()
		return 1

	def clear(self):
		'''Clear all messages'''
		self.messages.clear()

	def redo_lines(self, recolor=True):
		self.messages.redo_lines(recolor)
		self.parent.schedule_display()

	#MESSAGE ADDITION----------------------------------------------------------
	def msg_system(self, base):
		'''System message'''
		return self.msg_append(SystemMessage(base))

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

	def msg_append(self, post: Message):
		'''Append a message'''
		self.parent.schedule_display()
		return self.messages.append(post)

	def msg_prepend(self, post: Message):
		'''Prepend a message'''
		self.parent.schedule_display()
		return self.messages.prepend(post)

class _MessageScrollOverlay(DisplayOverlay):
	'''
	DisplayOverlay with the added capabilities to display messages in a
	LazyIterList and to scroll a ChatOverlay to the message index of such
	a message. Do not directly create these; use add_message_scroller.
	'''
	def __init__(self, overlay, lazy_list, early, late):
		self.lazy_list = lazy_list
		message, self.msg_index = lazy_list[0]
		self.early = early
		self.late = late
		super().__init__(overlay.parent, message, Message.INDENT)

		scroll_to = lambda: overlay.messages.scroll_to(self.msg_index) or -1
		self.add_keys({
			  'tab':	scroll_to
			, 'enter':	scroll_to
		})

	@key_handler('N', step=-1)
	@key_handler('a-j', step=-1)
	@key_handler('n', step=1)
	@key_handler('a-k', step=1)
	def next(self, step):
		attempt = self.lazy_list.step(step)
		if attempt:
			self.change_display(attempt[0])
			self.msg_index = attempt[1]
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
	def _(self):
		new = CommandOverlay(parent)
		new.text.append(self.list[self.it])
		self.swap(new)

	return command_list

@CommandOverlay.command("q")
def close(parent, *_):
	parent.stop()
