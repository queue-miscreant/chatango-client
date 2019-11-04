#!/usr/bin/env python3
#chatango.py
'''
Chatango extension to client. Receives data from a Chatango room via `ChatBot`
and displays it to the screen via `ChatangoOverlay`.
'''
from os import path
import asyncio
import re
import json
from collections import deque

import pytango
import client
from client import linkopen
__all__ = ["ChatBot", "ChatangoMessage", "ChatangoOverlay"
	, "get_color", "get_client"]

#SETTINGS AND CUSTOM SCRIPTS----------------------------------------------------
FILENAME = "chatango_creds"
#custom and credential saving setup
HOME_PATH = path.expanduser('~/.cubecli')
CUSTOM_PATH = path.join(HOME_PATH, "custom")
SAVE_PATH = path.join(HOME_PATH, FILENAME)
#code ripped from stackoverflow questions/1057431
CUSTOM_DOC = "ensures the `import custom` in will import all python files "\
"in the directory"
CUSTOM_INIT = '''"%s"

from os.path import dirname, basename, isfile
import glob
modules = glob.glob(dirname(__file__)+"/*.py")
__all__ = [basename(f)[:-3] for f in modules \
			if not f.endswith("__init__.py") and isfile(f)]
from . import *
''' % CUSTOM_DOC
def _write_init():
	with open(path.join(CUSTOM_PATH, "__init__.py"), "w") as i:
		i.write(CUSTOM_INIT)

#GLOBALS------------------------------------------------------------
BEGIN_COLORS = client.colors.defined
_CLIENT = None

class _Persistent:
	'''
	A JSON manifest-like abstraction. Acts like a dict for the most part.
	Add fields and their default value with add_field.
	'''
	def __init__(self):
		self._readwrite = {}	#fields that can be read/written to json
		self._entire = {}		#entire credentials file from read_json
		self._default = {}		#default value set by add_field
		self._data = {}			#volatile data to be written to file

	def __str__(self):
		ret = self._entire.copy()
		for i, j in ret.items():
			ret[i] = {
				  "Base": self._data[i]
				, "Data": j
			}
		return repr(ret)

	def __getitem__(self, key):
		return self._data.get(key)

	def __setitem__(self, key, value):
		self._data[key] = value

	def add_field(self, field, default, readwrite=3):
		'''Add a field to the JSON. `field` must be hashable (preferably str)'''
		self._readwrite[field] = readwrite
		if isinstance(default, (dict, list)):
			default = default.copy()
		self._default[field] = default
		self._data[field] = self._default[field]
		self._entire[field] = self._default[field]

	def clear(self, field):
		'''Clear a field, such that the next file write will be the default'''
		self._entire[field] = self._default[field]

	def read_json(self, filename):
		'''Read fields from JSON `filename`'''
		try:
			with open(filename) as i:
				json_data = json.load(i)
			for i, bit in self._readwrite.items():
				if bit&1:
					self._data[i] = json_data.get(i)
				self._entire[i] = json_data.get(i)
		except (FileNotFoundError, ValueError):
			pass
		except Exception as exc:
			raise IOError("Fatal error reading creds! Aborting...") from exc

	def write_json(self, filename):
		'''Write fields to JSON `filename`'''
		try:
			json_data = {}
			for i, bit in self._readwrite.items():
				if bit&2 or i not in self._entire:
					json_data[i] = self._data[i]
				else:	#"safe" credentials from last write
					json_data[i] = self._entire[i]
			encoder = json.JSONEncoder(ensure_ascii=False)
			with open(filename, 'w') as out:
				out.write(encoder.encode(json_data))
		except Exception as exc:
			raise IOError("Fatal error writing creds!") from exc

	def no_rw(self, field):
		'''Field will be neither read from file nor written to file'''
		self._readwrite[field] = 0

	def set_read(self, field):
		'''Allow field to be read from file'''
		self._readwrite[field] |= 1

	def set_write(self, field):
		'''Allow field to be written to file'''
		self._readwrite[field] |= 2

	def clear_read(self, field):
		'''Disallow field to be read from file'''
		self._readwrite[field] &= ~1

	def clear_write(self, field):
		'''Disallow field to be written to file'''
		self._readwrite[field] &= ~2

def make_creds():
	'''Create canonical save file as _Persistent and return'''
	creds = _Persistent()
	creds.add_field("user", default=None)
	creds.add_field("passwd", default=None)
	creds.add_field("room", default=None)
	creds.add_field("formatting", default=[
		  "DD9211"	#font color
		, "232323"	#name color
		, "0"		#font face
		, 12		#font size
	])
	creds.add_field("options", default={
		  "mouse":		False
		, "linkwarn":	linkopen.open_link.warning_count
		, "ignoresave":	False
		, "bell":		True
		, "256color":	False
		, "htmlcolor":	True
		, "anoncolor":	False
	})
	creds.add_field("ignores", default=[], readwrite=1)
	creds.add_field("filtered_channels", default=[0, 0, 0, 0])

	return creds

def create_colors():
	'''Create colors used by classes defined here'''
	global BEGIN_COLORS #pylint: disable=global-statement
	BEGIN_COLORS = client.colors.defined
	ordering = (
		  "blue"
		, "cyan"
		, "magenta"
		, "red"
		, "yellow"
	)
	for i in range(10):
		client.colors.def_color(ordering[i%5], intense=i//5)	#0-10: legacy
	client.colors.def_color("green", intense=True)
	client.colors.def_color("green")				#11:	>
	client.colors.def_color("none")					#12:	blank channel
	client.colors.def_color("red", "red")			#13:	red channel
	client.colors.def_color("blue", "blue")			#14:	blue channel
	client.colors.def_color("magenta", "magenta")	#15:	both channel
	client.colors.def_color("white", "white")		#16:	blank channel, visible

#color by user's name
def get_color(name, init=6, split=109, rot=6):
	'''Old trivial hash for assigning colors from string `name`'''
	if name.startswith("!anon"):
		number = int(name[5:])
		return BEGIN_COLORS + (number+rot)%11
	if name.startswith("#"):
		name = name[1:]
	total = init
	for i in map(ord, name):
		total ^= (i > split) and i or ~i
	return BEGIN_COLORS + (total+rot)%11

#ChatBot related functionality--------------------------------------------------
def get_client():
	'''Get the current client instance, or if none such exists, None'''
	global _CLIENT #pylint: disable=global-statement
	if isinstance(_CLIENT, ChatBot):
		return _CLIENT
	return None

class DequeSet(deque):
	'''Set, but whose elements can be moved to the front or end like a deque'''
	def __init__(self, iterable=None):
		if iterable is not None:
			super().__init__(iterable)
		else:
			super().__init__()

	def appendleft(self, new): #pylint: disable=arguments-differ
		'''Add or promote an element to the left side of the deque'''
		try:
			self.remove(new)
		except ValueError:
			pass
		super().appendleft(new)

	def append(self, new): #pylint: disable=arguments-differ
		'''Add or promote an element to the right side of the deque'''
		try:
			self.remove(new)
		except ValueError:
			pass
		super().append(new)

	def extend(self, iterable):
		'''Extend right side of deque with each element in iterable'''
		super().extend(filter(lambda x: x not in self, iterable))

	def extendleft(self, iterable):
		'''Extend left side of deque with each element in iterable'''
		super().extendleft(filter(lambda x: x not in self, iterable))

class ChatangoMessage(client.Message):
	'''Message subclass for chatango posts'''
	_LINE_RE = re.compile(r"^( [!#]?\w+?: (@\w* )*)?(.+)$", re.MULTILINE)
	_QUOTE_RE = re.compile(r"@\w+?: `[^`]+`")

	def __init__(self, post, bot, me, ishistory, alts=None): #pylint: disable=too-many-arguments
		#and is short-circuited
		isreply = (me is not None and (me in post.mentions)) or \
			(alts and any(i in post.mentions for i in alts if i))

		#remove egregiously large amounts of newlines (more than 2)
		#also edit sections with right to left override
		cooked = ""
		newline_count = 0
		rtlbuffer, rtl = "", False
		for i in post.post:
			if i == '\n':
				#right-to-left sequences end on newlines
				if rtl:
					cooked += rtlbuffer + (newline_count < 2 and i or "")
					rtl = False
					rtlbuffer = ""
				if newline_count < 2:
					cooked += i
				newline_count += 1
			#technically not right, since RTL marks should match marks, and
			#overrides overrides
			elif ord(i) in (8206, 8237):
				cooked += rtlbuffer
				rtlbuffer = ""
				rtl = False
			elif ord(i) in (8207, 8238):
				rtl = True
			else:
				newline_count = 0
				if rtl:
					rtlbuffer = i + rtlbuffer
				else:
					cooked += i
		if rtl:
			cooked += rtlbuffer

		#format as ' user: message'; the space is for the channel
		super().__init__(" {}: {}".format(str(post.user), cooked)
		#extra arguments to use in colorizers
			, bot=bot, post=post, reply=isreply, history=ishistory)

		if bot.options["bell"] and isreply and not ishistory and \
		not self.filtered:
			bot.overlay.parent.sound_bell()

	def colorize(self):
		raw_white = client.colors.raw_num(0)
		#these names are important
		name_color = client.two56(self.post.n_color)
		font_color = client.two56(self.post.f_color)
		visited_link = client.grayscale(12)

		#use name colors?
		username = str(self.post.user)
		if not self.bot.options["htmlcolor"] \
		or (self.bot.options["anoncolor"] and username[0] in "!#"):
			name_color = get_color(username)
			font_color = get_color(username)

		#greentext, font color
		text_color = lambda x: x[0] == '>' and BEGIN_COLORS+11 or font_color
		self.color_by_regex(self._LINE_RE, text_color, group=3)

		#links in white
		link_color = lambda x: visited_link \
			if linkopen.open_link.is_visited(x) else raw_white
		self.color_by_regex(linkopen.LINK_RE, link_color, font_color, 1)

		#underline quotes
		self.effect_by_regex(self._QUOTE_RE, 1)

		#make sure we color the name right
		self.insert_color(1, name_color)
		#insurance the @s before a > are colored right
		#		space/username/:(space)
		msg_start = 1+len(username)+2
		if not self.colored_at(msg_start):
			self.insert_color(msg_start, font_color)
		if self.reply:
			self.add_global_effect(0, 1)
		if self.history:
			self.add_global_effect(1, 1)

		#channel
		self.insert_color(0, BEGIN_COLORS + self.post.channel + 12)

	def filter(self):
		username = str(self.post.user)
		if username[0] in "!#":
			username = username[1:]
		return any((
			#filtered channels
			  self.bot.filtered_channels[self.post.channel]
			#ignored users
			, username.lower() in self.bot.ignores
		))

class ChatBot(pytango.Manager): #pylint: disable=too-many-instance-attributes, too-many-public-methods
	'''Bot for interacting with the chat'''
	members = DequeSet()
	def __init__(self, parent, creds):
		super().__init__(creds["user"], creds["passwd"], loop=parent.loop)

		self.creds = creds
		#default to the given user name
		self.alts = []
		#list references
		self.ignores = set(creds["ignores"])
		self.filtered_channels = creds["filtered_channels"]
		self.options = creds["options"]

		self.connecting = False
		self.joined_group = None
		self.channel = 0

		self.overlay = ChatangoOverlay(parent, self)
		self.overlay.add()

		#disconnect from all groups on done
		client.on_done(self.graceful_exit())

		#tabbing for members, ignoring the # and ! induced by anons and temps
		client.Tokenize('@', self.members)
		self.loop.create_task(self.connect())

	@property
	def me(self):
		if self.joined_group is not None:
			uname = self.joined_group.username
			if uname[0] in "#!":
				uname = uname[1:]
			return uname
		return None

	async def connect(self):
		if self.connecting:
			return
		self.connecting = True
		self.members.clear()
		self.overlay.msg_system("Connecting")
		await self.join_group(self.creds["room"])
		self.connecting = False

	async def reconnect(self):
		await self.leave_group(self.joined_group)
		self.overlay.clear()
		await self.connect()

	async def join_group(self, group_name): #pylint: disable=arguments-differ
		await self.leave_group(self.joined_group)
		self.creds["room"] = group_name
		self.overlay.clear()
		try:
			await super().join_group(group_name)
		except (ConnectionError, ValueError):
			self.overlay.msg_system("Failed to connect to room '{}'".format(
				self.creds["room"]))

	async def graceful_exit(self):
		#this is a set and not a list reference, so we update the list now
		self.creds["ignores"] = list(self.ignores)
		await self.leave_all()

	def set_formatting(self):
		group = self.joined_group

		group.f_color = self.creds["formatting"][0]
		group.n_color = self.creds["formatting"][1]
		group.f_face = self.creds["formatting"][2]
		group.f_size = self.creds["formatting"][3]

	def send_post(self, text):
		if self.joined_group is None:
			return
		self.joined_group.send_post(text, self.channel)

	def send_pm(self, user, text):
		if self.privates is None:
			return
		self.pm.send_post(user, text)
		dummy = pytango.Post.private(self.privates, (self.me, 0, 0, 0, 0, text))
		self.loop.create_task(self.on_pm(None, dummy, False))

	async def on_connect(self, group):
		self.joined_group = group
		self.set_formatting()
		self.overlay.left = "{}@{}".format(group.username, group.name)
		#show last message time
		self.overlay.msg_system("Connected to "+group.name)
		self.overlay.msg_time(group.last_message, "Last message at ")
		self.overlay.msg_time()

	async def on_pm_connect(self, _):
		self.overlay.msg_system("Connected to PMs")

	'''
	async def on_pm(self, _, post, historical):
		msg = " {}: {}".format(str(post.user), post.post)
		self.overlay.msg_append(msg, post, True, historical)
	'''

	async def on_message(self, _, post):
		#double check for anons
		username = str(post.user).lower()
		if username[0] in '!#':
			username = username[1:]
		self.members.appendleft(username)
		self.overlay.parse_links(post.post)
		self.overlay.msg_append(ChatangoMessage(post, self, self.me, False
			, alts=self.alts))

	async def on_history_done(self, _, history):
		for post in history:
			username = str(post.user).lower()
			if username[0] in '!#':
				username = username[1:]
			self.members.append(username)
			self.overlay.parse_links(post.post, True)
			self.overlay.msg_prepend(ChatangoMessage(post, self, self.me, True
				, alts=self.alts))
		self.overlay.can_select = True

	async def on_flood_warning(self, _):
		self.overlay.msg_system("Flood ban warning issued")

	async def on_flood_ban(self, group, secs):
		await self.on_flood_ban_repeat(group, secs)

	async def on_flood_ban_repeat(self, _, secs):
		self.overlay.msg_system("You are banned for {} seconds".format(secs))

	async def on_participants(self, group):
		'''On received joined members.'''
		self.members.extend(map(lambda x: x.name.lower(), group.users))
		self.overlay.redo_lines()

	async def on_usercount(self, group):
		'''On user count changed.'''
		self.overlay.right = str(group.usercount)

	async def on_member_join(self, _, user):
		if user != "anon":
			self.members.appendleft(str(user).lower())
		#notifications
		self.overlay.parent.blurb.push("{} has joined".format(str(user)))

	async def on_member_leave(self, _, user):
		self.overlay.parent.blurb.push("{} has left".format(str(user)))

	async def on_connection_error(self, _, error):
		if isinstance(error, (ConnectionResetError, type(None))):
			self.overlay.messages.stop_select()
			self.overlay.msg_system("Connection lost; press ^r to reconnect")
		else:
			self.overlay.msg_system(
				"Connection error occurred. Try joining another room with ^T")

	async def on_login_fail(self, _):
		self.overlay.msg_system("Login as '{}' failed. "\
			"Try again with ^p".format(self.username))

#List Overlay Extensions-------------------------------------------------------
class LinkOverlay(client.VisualListOverlay):
	'''ListOverlay of links that renders whether they have been visited'''
	def __init__(self, parent, last_links):
		builder = lambda raw: list(reversed(raw))
		super().__init__(parent, last_links
			, modes=["default"] + linkopen.get_defaults(), builder=builder)

		find_new = lambda i: linkopen.open_link.is_visited(self[i]) ^\
						linkopen.open_link.is_visited(self.current)
		prev_new, next_new = self.goto_lambda(find_new)

		self.add_keys({
			 "i":		self.open_images
			, "a-k":	prev_new
			, "a-j":	next_new
		})

	def _callback(self, result): #pylint: disable=method-hidden
		'''Open link with selected opener'''
		linkopen.open_link(self.parent, result, self.mode)
		self.clear()

	def open_images(self):
		'''Open all images that have not been visited'''
		linkopen.open_link(self.parent, [link for link in self.list \
			if (linkopen.get_extension(link).lower() in ("png", "jpg", "jpeg")) \
			and (not linkopen.open_link.is_visited(link))], self.mode)

	def _draw_line(self, line, number):
		'''Draw visited links in a slightly grayer color'''
		#remove the protocol
		line.setstr(str(line).replace("https://", "").replace("http://", ""))
		#draw whether this link is visited
		if linkopen.open_link.is_visited(self[number]):
			line.insert_color(0, client.grayscale(12))
		super()._draw_line(line, number)

#Formatting InputMux------------------------------------------------------------
Formatting = client.InputMux()	#pylint: disable=invalid-name
@Formatting.listel("color")
def fontcolor(context):
	"Font Color"
	return context.bot.creds["formatting"][0]
@fontcolor.setter
def _(context, value):
	context.bot.creds["formatting"][0] = \
		client.ColorSliderOverlay.to_hex(value)
	context.bot.set_formatting()

@Formatting.listel("color")
def namecolor(context):
	"Name Color"
	return context.bot.creds["formatting"][1]
@namecolor.setter
def _(context, value):
	context.bot.creds["formatting"][1] = \
		client.ColorSliderOverlay.to_hex(value)
	context.bot.set_formatting()

@Formatting.listel("enum")
def fontface(context):
	"Font Face"
	tab = pytango.FONT_FACES
	index = context.bot.creds["formatting"][2]
	return tab, int(index)
@fontface.setter
def _(context, value):
	context.bot.creds["formatting"][2] = str(value)
	context.bot.set_formatting()

@Formatting.listel("enum")
def fontsize(context):
	"Font Size"
	tab = pytango.FONT_SIZES
	index = context.bot.creds["formatting"][3]
	return list(map(str, tab)), tab.index(index)
@fontsize.setter
def _(context, value):
	context.bot.creds["formatting"][3] = pytango.FONT_SIZES[value]
	context.bot.set_formatting()

#Options InputMux---------------------------------------------------------------
Options = client.InputMux()	#pylint: disable=invalid-name
@Options.listel("bool")
def mouse(context):
	"Mouse:"
	return context.bot.options["mouse"]
@mouse.setter
def _(context, value):
	context.bot.options["mouse"] = value
	context.parent.mouse = value

@Options.listel("str")
def linkwarn(context):
	"Multiple link open warning threshold:"
	return context.bot.options["linkwarn"]
@linkwarn.setter
def _(context, value):
	try:
		#one for saving, one for function
		context.bot.options["linkwarn"] = int(value)
		linkopen.open_link.warning_count = int(value)
	except ValueError:
		pass

@Options.listel("bool")
def ignoresave(context):
	"Save ignore list:"
	return context.bot.options["ignoresave"]
@ignoresave.setter
def _(context, value):
	creds = context.bot.creds
	context.bot.options["ignoresave"] = value
	if value:
		creds.set_write("ignores")
	else:
		creds.clear_write("ignores")
		creds.clear("ignores")

@Options.listel("bool")
def bell(context):
	"Console bell on reply:"
	return context.bot.options["bell"]
@bell.setter
def _(context, value):
	context.bot.options["bell"] = value

@Options.listel("bool")
def two56(context):
	"256 colors:"
	return context.bot.options["256color"]
@two56.setter
def _(context, value):
	context.bot.options["256color"] = value
	client.colors.two56on = value
	context.redo_lines()

@Options.listel("bool")
def htmlcolor(context):
	"HTML colors:"
	return context.bot.options["htmlcolor"]
@htmlcolor.setter
def _(context, value):
	context.bot.options["htmlcolor"] = value
	context.redo_lines()
@htmlcolor.drawer
def _(mux, value, coloring):
	'''Gray out if invalid due to 256 colors being off'''
	htmlcolor.draw_bool(mux, value, coloring)
	if not two56.get(mux.context):
		coloring.clear()
		coloring.insert_color(0, client.grayscale(12))

@Options.listel("bool")
def anoncolor(context):
	"Colorize anon names:"
	return context.bot.options["anoncolor"]
@anoncolor.setter
def _(context, value):
	context.bot.options["anoncolor"] = value
	context.redo_lines()
@anoncolor.drawer
def _(mux, value, coloring):
	'''Gray out if invalid due to 256 colors and HTML colors being off'''
	anoncolor.draw_bool(mux, value, coloring)
	if not (two56.get(mux.context) and htmlcolor.get(mux.context)):
		coloring.clear()
		coloring.insert_color(0, client.grayscale(12))

#Extended overlay---------------------------------------------------------------
@ChatangoMessage.key_handler("a-enter", 1)
@ChatangoMessage.key_handler("enter")
def open_selected_links(message, overlay):
	'''Open links in selected message'''
	msg = message.post.post
	all_links = linkopen.LINK_RE.findall(msg)
	linkopen.open_link(overlay.parent, all_links)

@ChatangoMessage.key_handler("tab")
def	reply_to_message(message, overlay):
	'''Reply to selected message'''
	msg, name = message.post.post, message.post.user
	if name[0] in "!#":
		name = name[1:]
	if message.bot.me:
		msg = msg.replace("@"+message.bot.me, "")
	overlay.text.append("@{}: `{}`".format(name, msg.replace('`', "")))

@ChatangoMessage.key_handler("^n")
def add_ignore(message, overlay):
	'''Add ignore from selected message'''
	try:
		#allmessages contain the colored message and arguments
		name = message.post.user
		if name[0] in "!#":
			name = name[1:]
		if name in message.bot.ignores:
			return
		message.bot.ignores.add(name)
		overlay.redo_lines()
	except IndexError:
		pass

@ChatangoMessage.key_handler("mouse-left")
def _click_link(message, overlay, pos):
	'''Click on a link as you would a hyperlink in a web browser'''
	if pos == -1:
		return 1
	link = ""
	smallest = -1
	#look over all link matches; take the middle and find the smallest delta
	for i in linkopen.LINK_RE.finditer(str(message)):
		linkpos = (i.start() + i.end()) // 2
		distance = abs(linkpos - pos)
		if distance < smallest or smallest == -1:
			smallest = distance
			link = i.group()
	if link:
		linkopen.open_link(overlay.parent, link)
		overlay.redo_lines()
	return 1

class ChatangoOverlay(client.ChatOverlay):
	def __init__(self, parent, bot):
		self.last_links = []

		super().__init__(parent)
		self.can_select = False
		self.bot = bot
		self.add_keys({
			  "enter":		self._enter
			, "f2":			self._show_links
			, "f3":			self._show_members
			, "f4":			self._show_formatting
			, "f5":			self._show_channels
			, "f6":			self._replies_scroller
#			, "f7":			self.pmConnect
			, "f12":		self._show_options
			, "^f":			self._search_scroller
			, "^t":			self.join_group
			, "^p":			self.userpass
			, "^g":			self.open_last_link
			, "^r":			self.reload_client
		})

		linkopen.open_link.add_redraw_method(self.redo_lines)

	def _max_select(self):
		#when we've gotten too many messages
		group = self.bot.joined_group
		if group:
			self.can_select = False
			group.get_more()
			#wait until we're done getting more
			self.parent.blurb.push("Fetching more messages")
		super()._max_select()

	def clear(self):
		super().clear()
		self.last_links.clear()

	def _enter(self):
		'''Open selected message's links or send message'''
		text = str(self.text)
		#if it's not just spaces
		if not text.isspace():
			#add it to the history
			self.text.clear()
			self.history.append(text)
			#call the send
			self.bot.send_post(text)

	def _show_links(self):
		'''List accumulated links'''
		LinkOverlay(self.parent, self.last_links).add()

	def _show_members(self):
		'''List members of current group'''
		if self.bot.joined_group is None:
			return
		#a current version of the users. will be 1:1 with the listoverlay
		users = list(sorted(self.bot.joined_group.users, key=lambda x: x.name.lower()))
		box = client.ListOverlay(self.parent, users)

		@box.key_handler("enter")
		def select(me): #pylint: disable=unused-variable
			'''Reply to user'''
			current = me.selected.name
			if current[0] in "!#":
				current = current[1:]
			#reply
			self.text.append("@%s " % current)
			return -1

		@box.key_handler("tab")
		def tab(me): #pylint: disable=unused-variable
			'''Ignore/unignore user'''
			current = users[me.it].name.lower()
			self.bot.ignores.symmetric_difference_update((current,))
			self.redo_lines()

		@box.key_handler("a")
		def get_avatar(me): #pylint: disable=unused-variable
			'''Get avatar'''
			current = users[me.it]
			linkopen.open_link(self.parent, current.avatar)

		@box.line_drawer
		def draw_ignored(_, string, i): #pylint: disable=unused-variable
			string.setstr(format(users[i]))
			selected = users[i].name.lower()
			if selected in self.bot.ignores:
				string.add_indicator('i', BEGIN_COLORS+3)

		box.add()

	def _show_formatting(self):
		'''Chatango formatting settings'''
		Formatting.add(self.parent, self)

	def _show_channels(self):
		'''List channels'''
		box = client.ListOverlay(self.parent, pytango.CHANNEL_NAMES)
		box.it = self.bot.channel

		@box.key_handler("enter")
		def select(me): #pylint: disable=unused-variable
			'''Set channel'''
			self.bot.channel = me.it
			return -1

		@box.key_handler("tab")
		def tab(me): #pylint: disable=unused-variable
			'''Ignore/unignore channel'''
			self.bot.filtered_channels[me.it] = \
				not self.bot.filtered_channels[me.it]
			self.redo_lines()

		@box.line_drawer
		def draw_active(_, string, i): #pylint: disable=unused-variable
			if self.bot.filtered_channels[i]:
				return
			col = BEGIN_COLORS + (i and i+12 or 16)
			string.add_indicator(' ', col)

		box.add()

	def _show_options(self):
		'''Options'''
		Options.add(self.parent, self)

	def _replies_scroller(self):
		'''List replies in message scroller'''
		callback = lambda message: isinstance(message, ChatangoMessage) \
			and message.reply
		client.add_message_scroller(self, callback
			, empty="No replies have been accumulated"
			, early="Earliest reply selected"
			, late="Latest reply selected")

	def _search_scroller(self):
		'''Find message with some text'''
		#minimalism
		box = client.InputOverlay(self.parent)
		box.text.setnonscroll("^f: ")

		@box.callback
		def search(string): #pylint: disable=unused-variable
			callback = lambda message: -1 != str(message).lower().find(string)
			client.add_message_scroller(self, callback
				, empty="No message containing `%s` found" % string
				, early="No earlier instance of `%s`" % string
				, late="No later instance of `%s`" % string)

		box.add()

	#LINK RELATED--------------------------------------------------------------
	def parse_links(self, raw, prepend=False):
		'''
		Add links to last_links. Prepend argument for adding links backwards,
		like with historical messages.
		'''
		links = []
		#don't add the same link twice
		for i in linkopen.LINK_RE.findall(raw+' '):
			if i not in links:
				links.append(i)
		if prepend:
			links.reverse()
			self.last_links = links + self.last_links
		else:
			self.last_links.extend(links)

	def open_last_link(self):
		'''Open last link'''
		links = self.last_links
		if not links:
			return
		last = links[-1]
		linkopen.open_link(self.parent, last)
		self.redo_lines()

	#PARENT BOT RELATED--------------------------------------------------------
	def reload_client(self):
		'''Reload current group'''
		self.parent.loop.create_task(self.bot.reconnect())

	def join_group(self):
		'''Join a new group'''
		inp = client.InputOverlay(self.parent, "Enter group name")
		inp.callback(self.bot.join_group)
		inp.add()

	def userpass(self):
		'''Re-log in'''
		async def callback():
			data = [None, None]
			for i, j in enumerate(("Username", "Password")):
				over = client.InputOverlay(self.parent, j, i == 1)
				over.add()

				try:
					data[i] = await over.result
				except asyncio.CancelledError:
					self.blurb.push("Login aborted")
					return
			self.bot.username, self.bot.password = data
			self.bot.creds["user"], self.bot.creds["passwd"] = data
			await self.bot.reconnect()

		self.parent.loop.create_task(callback())

#COMMANDS-------------------------------------------------------------------
@client.command("ignore")
def _(parent, person, *args): #pylint: disable=unused-argument
	'''Ignore person or everyone'''
	chatbot = get_client()
	if not chatbot:
		return

	if person[0] == '@':
		person = person[1:]
	if person in chatbot.ignores:
		return
	chatbot.ignores.add(person)
	chatbot.overlay.redo_lines()

@client.command("unignore")
def _(parent, person, *args): #pylint: disable=unused-argument
	'''Unignore person or everyone'''
	chatbot = get_client()
	if not chatbot:
		return

	if person[0] == '@':
		person = person[1:]
	if person in ("all", "everyone"):
		chatbot.ignores.clear()
		chatbot.overlay.redo_lines()
		return
	if person not in chatbot.ignores:
		return
	chatbot.ignores.remove(person)
	chatbot.main_overlay.redo_lines()

@client.command("keys")
def _(parent, *args): #pylint: disable=unused-argument
	'''Get list of the ChatangoOverlay's keys'''
	#keys are instanced at runtime
	chatbot = get_client()
	if not chatbot:
		return None

	return chatbot.overlay.open_help()

@client.command("avatar", client.tab_file)
def _(parent, *args):
	'''Upload file as user avatar'''
	chatbot = get_client()
	if not chatbot:
		return

	location = path.expanduser(' '.join(args))
	location = location.replace("\\ ", ' ')

	if not location.find("file://"):
		location = location[7:]

	success = chatbot.upload_avatar(location)
	if success:
		parent.blurb.push("Successfully updated avatar")
	else:
		parent.blurb.push("Failed to update avatar")

async def start_client(manager, creds):
	#fill in credential holes
	for i, j in zip(("user", "passwd", "room")
	, ("Username", "Password", "Room name")):
		#skip if supplied
		if creds[i] is not None:
			continue
		inp = client.InputOverlay(manager.screen, j, password=(i == "passwd"))
		inp.add()

		try:
			creds[i] = await inp.result
		except asyncio.CancelledError:
			manager.stop()
			return

	#options
	if creds["options"]["ignoresave"]:
		creds.set_write("ignores")

	linkopen.open_link.warning_count = creds["options"]["linkwarn"]
	client.colors.two56on = creds["options"]["256color"]
	manager.screen.mouse = creds["options"]["mouse"]

	global _CLIENT #pylint: disable=global-statement
	_CLIENT = ChatBot(manager.screen, creds)

def main():
	#parse arguments and start client
	import argparse
	import os
	import sys

	if not path.exists(HOME_PATH):
		os.mkdir(HOME_PATH)
	if not path.exists(CUSTOM_PATH):
		os.mkdir(CUSTOM_PATH)
		_write_init()

	parser = argparse.ArgumentParser(description="Start the chatango client")
	parser.add_argument("-c", dest="login", help="Set username and password. "\
		"If both are absent, you log in as an anon. If only password is "\
		"absent, you set your name without having an account."
		, nargs='*', metavar=("username", "password"), default=None)
	parser.add_argument("-g", dest="group", help="Set group name"
		, nargs=1, metavar="groupname", default=None)
	parser.add_argument("-r", help="Re-input credentials"
		, dest="getcreds", action="store_true")
	parser.add_argument("-nc", help="Skip custom folder imports"
		, dest="custom", action="store_false")

	args = parser.parse_args()
	creds = make_creds()

	if args.login is not None:
		#no readwrite to user and pass
		creds.no_rw("user")
		creds.no_rw("passwd")
		# only username
		if len(args.login) == 1:
			creds["user"], creds["passwd"] = \
				args.login[0], ""
		# username and pasword
		elif len(args.login) == 2:
			creds["user"], creds["passwd"] = \
				args.login
		else:
			creds["user"], creds["passwd"] = \
				"", ""

	if args.group is not None:
		creds.clear_read("room")	#write only to room
		creds["room"] = args.group[0]

	if args.getcreds:
		creds.no_rw("user")	#write only to creds
		creds.no_rw("passwd")
		creds.no_rw("room")

	creds.read_json(SAVE_PATH)

	#exec files in custom directory
	if args.custom:
		sys.path.append(HOME_PATH)
		import custom	#pylint: disable=import-error
		if custom.__doc__ != CUSTOM_DOC:
			_write_init()
			print("\x1b[31mAborted due to custom docstring mismatch. "\
				"Please rerun.\x1b[m")
			return

	#start
	create_colors()
	try:
		client.Manager.start(start_client, creds)
	finally:
		creds.write_json(SAVE_PATH)

if __name__ == "__main__":
	main()
