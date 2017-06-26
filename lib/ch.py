#!/usr/bin/env python3
#ch.py
'''
A rewrite of the chatango library based on cellsheet's chlib.py and lumirayz's
ch.py. Event based library for chatango rooms. Features channel support and 
fetching history messages among all other necessary functionalities.
'''
#TODO	better modtools
#TODO	property docstrings
#TODO	I have no idea why, but PMs are failing in all implementations.
#		Attempts to connect via websockets in a browser console also failed
#		abandoning attempts to fix for a while
#TODO	let protocol objecs handle responses, let group objects handle data
#
################################
#Python Imports
################################
import os
import random
import re
import urllib.request
import asyncio

BigMessage_Cut = 0
BigMessage_Multiple = 1

POST_TAG_RE = re.compile("(<n([a-fA-F0-9]{1,6})\/>)?(<f x([0-9a-fA-F]{2,8})=\"([0-9a-zA-Z]*)\">)?")
XML_TAG_RE = re.compile("(<.*?>)")
THUMBNAIL_FIX_RE = re.compile(r"(https?://ust.chatango.com/.+?/)t(_\d+.\w+)")

weights = [['5', 75], ['6', 75], ['7', 75], ['8', 75], ['16', 75], ['17', 75], ['18', 75], ['9', 95], ['11', 95], ['12', 95], ['13', 95], ['14', 95], ['15', 95], ['19', 110], ['23', 110], ['24', 110], ['25', 110], ['26', 110], ['28', 104], ['29', 104], ['30', 104], ['31', 104], ['32', 104], ['33', 104], ['35', 101], ['36', 101], ['37', 101], ['38', 101], ['39', 101], ['40', 101], ['41', 101], ['42', 101], ['43', 101], ['44', 101], ['45', 101], ['46', 101], ['47', 101], ['48', 101], ['49', 101], ['50', 101], ['52', 110], ['53', 110], ['55', 110], ['57', 110], ['58', 110], ['59', 110], ['60', 110], ['61', 110], ['62', 110], ['63', 110], ['64', 110], ['65', 110], ['66', 110], ['68', 95], ['71', 116], ['72', 116], ['73', 116], ['74', 116], ['75', 116], ['76', 116], ['77', 116], ['78', 116], ['79', 116], ['80', 116], ['81', 116], ['82', 116], ['83', 116], ['84', 116]]
specials = {"de-livechat": 5, "ver-anime": 8, "watch-dragonball": 8, "narutowire": 10, "dbzepisodeorg": 10, "animelinkz": 20, "kiiiikiii": 21, "soccerjumbo": 21, "vipstand": 21, "cricket365live": 21, "pokemonepisodeorg": 22, "watchanimeonn": 22, "leeplarp": 27, "animeultimacom": 34, "rgsmotrisport": 51, "cricvid-hitcric-": 51, "tvtvanimefreak": 54, "stream2watch3": 56, "mitvcanal": 56, "sport24lt": 56, "ttvsports": 56, "eafangames": 56, "myfoxdfw": 67, "peliculas-flv": 69, "narutochatt": 70}

class _Generate:
	def uid():
		'''Generate user ID'''
		return str(int(random.randrange(10 ** 15, (10 ** 16) - 1)))

	def aid(n, uid):
		'''Generate anon ID'''
		try:
			n = n.rsplit('.', 1)[0]
			n = n[-4:]
			int(n)	#insurance that n is int-able
		except:
			n = "3452"
		return "".join(map(lambda i,v: str(int(i) + int(v))[-1],
					   n, str(uid)[4:8]))

	def serverNum(group):
		'''Return server number'''
		if group in specials.keys():
			return specials[group]
		group = re.sub("-|_", 'q', group)
		wt, gw = sum([n[1] for n in weights]), 0
		try:
			num1 = 1000 if len(group) < 7 else max(int(group[6:9], 36), 1000)
			num2 = (int(group[:5],36) % num1) / num1
		except ValueError:
			return
		for i, v in weights:
			gw += v / wt
			if gw >= num2:
				return i
HTML_CODES = [
	("&#39;","'"),
	("&gt;",'>'),
	("&lt;",'<'),
	("&quot;",'"'),
	("&apos;","'"),
	("&amp;",'&'),
]
def formatRaw(raw):
	'''
	Format a raw html string into one with newlines 
	instead of <br>s, and all tags formatted out
	'''
	if len(raw) == 0: return raw
	#replace <br>s with actual line breaks
	#otherwise, remove html
	for i in XML_TAG_RE.findall(raw):
		raw = raw.replace(i,i == "<br/>" and '\n' or "")
	raw.replace("&nbsp;",' ')
	for i,j in HTML_CODES:
		raw = raw.replace(i,j)
	#remove trailing \n's
	while len(raw) and raw[-1] == "\n":
		raw = raw[:-1]
	#thumbnail fix in chatango
	raw = THUMBNAIL_FIX_RE.subn(r"\1l\2",raw)[0]
	return raw

def _formatMsg(raw, bori):
	'''
	Create a Post object from a raw b or i command received.
	Post objects have support for channels and formatting parsing
	'''
	post = type("Post",(object,),
		{"time":	float(raw[0])
		,"user":	None
		,"msgid":	None
		,"uid":		raw[3]
		,"unid":	raw[4]
		,"pnum":	None
		,"ip":		raw[6]
		,"channel":	0
		,"post":	formatRaw(':'.join(raw[9:]))
		,"nColor":	''
		,"fSize":	12
		,"fFace":	0
		,"fColor":	""})

	if bori == 'b':
		post.pnum = raw[5]
	elif bori == 'i':
		post.msgid = raw[5]

	tag = POST_TAG_RE.search(raw[9])
	if tag:
		post.nColor = tag.group(2) or post.nColor
		sizeAndColor = tag.group(4)
		if sizeAndColor:
			if len(sizeAndColor) % 3 == 2:	#color only
				post.fSize = int(sizeAndColor[:2])
				post.fColor = sizeAndColor[2:]
			else:
				post.fColor = sizeAndColor
		post.fFace = int(tag.group(5) or post.fFace)
	#user parsing
	user = raw[1].lower()
	if not user:
		if raw[2] != "":
			user = '#' + raw[2].lower()
		else:
			user = "!anon" + _Generate.aid(post.nColor, post.uid)
		post.nColor = ''
	post.user = user
	channel = (int(raw[7]) >> 8) & 31
	post.channel = channel&1|((channel&8)>>2)|((channel&16)>>3)

	return post

class ChatangoProtocol(asyncio.Protocol):
	_pingDelay = 15

	def __init__(self, manager, loop=None):
		self._loop = manager.loop if loop is None else loop

		self._uid = _Generate.uid()
		self._manager = manager
		#socket stuff
		self._transport = None
		self._rbuff = b""

		#account information
		self._anon = None
		self._premium = False
		self._messageBackground = False
		self._messageRecord = False
		#formatting
		self._nColor = None	
		self._fSize  = 11
		self._fColor = ""
		self._fFace  = 0

		self._canPing = True

	####################################
	# Properties
	####################################

	nColor = property(lambda self: self._nColor)
	fColor = property(lambda self: self._fColor)
	fSize  = property(lambda self: self._fSize)
	fFace  = property(lambda self: self._fFace)
		
	@nColor.setter
	def nColor(self,arg):
		if not self._anon:	self._nColor = arg
	@fColor.setter
	def fColor(self,arg):	self._fColor = arg
	@fSize.setter
	def fSize(self,arg): 	self._fSize = min(22,max(9,arg))
	@fFace.setter
	def fFace(self,arg): 	self._fFace = arg

	#########################################
	#	Callbacks
	#########################################

	def data_received(self, data):
		'''Parse argument as data from the socket and call method'''
		self._rbuff += data
		commands = self._rbuff.split(b'\x00')
		for command in commands[:-1]:
			args = command.decode('utf-8').rstrip("\r\n").split(':')
			try:
				if command == b"":
					self._canPing = True		#received ping on time
					continue
				receive = getattr(self, "_recv_"+args[0])
				self._loop.create_task(receive(args[1:]))
			except AttributeError: pass
		self._rbuff = commands[-1]

	def connection_lost(self, exc):
		self._loop.call_soon(self._pingTask.cancel)
		#TODO bind exc to names
		from .client import dbmsg
		dbmsg(exc)
		if not self._canPing:
			self.callEvent("onConnectionError","lost")

	#########################################
	#	I/O
	#########################################

	def sendCommand(self, *args, firstcmd = False):
		'''Send data to socket'''
		if firstcmd:
			self._transport.write(bytes(':'.join(args)+'\x00', "utf-8"))
		else:
			self._transport.write(bytes(':'.join(args)+'\r\n\x00', "utf-8"))

	def callEvent(self, event, *args, **kw):
		'''Attempt to call manager's method'''
		try:
			event = getattr(self._manager, event)
			self._loop.create_task(event(self, *args, **kw))
		except AttributeError: pass

	def disconnect(self):
		if self._transport:
			self._transport.close()

	@asyncio.coroutine
	def ping(self):
		'''Send a ping, or fail and close the transport'''
		while True:
			if self._canPing:
				self._canPing = False
				self.sendCommand("")
			else:
				self._transport.close()
			
			yield from asyncio.sleep(self._pingDelay)
	
	@asyncio.coroutine
	def _recv_premium(self, args):
		'''Receive premium command. Called for both PM and Group'''
		#TODO write setBgMode and setRecordingMode
		if float(args[1]) > asyncio.time():
			self._premium = True
			if self._messageBackground: self.setBgMode(1)
			if self._messageRecord: self.setRecordingMode(1)
		else:
			self._premium = False

class GroupProtocol(ChatangoProtocol):
	_maxLength = 2000
	def __init__(self, room, manager, loop=None):
		super(GroupProtocol,self).__init__(manager,loop)
		#user information
		self._name = room
		self._owner = None
		self._mods = set()
		self._bannedWords = []
		self._banlist = []
		self._users = []
		self._userSessions = {}
		self._usercount = 0

		#intermediate message stuff and aux data for commands
		self._messages = {}
		self._history = []
		self._timesGot = 0
		self._last = 0

		#########################################
		#	Properties
		#########################################

	username  = property(lambda self: self._anon or self._manager.username)
	name      = property(lambda self: self._name)
	owner     = property(lambda self: self._owner)
	modlist   = property(lambda self: set(self._mods))		#cloned set
	userlist  = property(lambda self: list(self._users))	#cloned list
	usercount = property(lambda self: self._usercount)
	banlist   = property(lambda self: [banned[2] for banned in self._banlist])	#by name; cloned
	last      = property(lambda self: self._last)

	def connection_made(self, transport):
		self._transport = transport
		self.sendCommand("bauth", self._name, self._uid, self._manager.username,
			self._manager.password, firstcmd = True)

	#--------------------------------------------------------------------------

	@asyncio.coroutine
	def _recv_ok(self, args):
		'''Acknowledgement from server that login succeeded'''
		if args[2] == 'C' and (not self._manager.password) and (not self._manager.username):
			self._anon = "!anon" + _Generate.aid(args[4], args[1])
			self._nColor = "CCC"
		elif args[2] == 'C' and (not self._manager.password):
			self.sendCommand("blogin", self._manager.username)
		elif args[2] != 'M': #unsuccesful login
			self.callEvent("onLoginFail")
			self.transport.close()
			return
		self._owner = args[0]
		self._uid = args[1]	
		self._mods = set(mod.split(',')[0].lower() for mod in args[6].split(';'))

		self._pingTask = self._loop.create_task(self.ping()) #create a ping

	@asyncio.coroutine
	def _recv_denied(self, args):
		'''Acknowledgement that login was denied'''
		self.transport.close()
		self.callEvent("onDenied")
	
	@asyncio.coroutine
	def _recv_inited(self, args):
		'''Command fired on room inited, after recent messages have sent'''
		#TODO weed out null commands
		self.sendCommand("gparticipants")	#open up feed for members joining/leaving
		self.sendCommand("getpremium", '1')	#try to turn on premium
		self.sendCommand("getbannedwords")	#what it says on the tin
		self.sendCommand("getratelimit")	#i dunno
		self.callEvent("onConnect")
		self.callEvent("onHistoryDone", list(self._history))
		self._history.clear()

	@asyncio.coroutine
	def _recv_gparticipants(self, args):
		'''Command that contains information of current room members'''
		#gparticipants splits people by ;
		people = ':'.join(args[1:]).split(';')
		for person in people:
			person = person.split(':')
			if person[3] != "None" and person[4] == "None":
				self._users.append(person[3].lower())
				self._userSessions[person[2]] = person[3].lower()
		self.callEvent("onParticipants")

	@asyncio.coroutine
	def _recv_participant(self, args):
		'''Command fired on new member join'''
		bit = args[0]
		if bit == '0':	#left
			user = args[3].lower()
			if args[3] != "None" and user in self._users:
				self._users.remove(user)
				self.callEvent("onMemberLeave", user)
			else:
				self.callEvent("onMemberLeave", "anon")
		elif bit == '1':	#joined
			user = args[3].lower()
			if args[3] != "None":
				self._users.append(user)
				self.callEvent("onMemberJoin", user)
			else:
				self.callEvent("onMemberJoin", "anon")
		elif bit == '2':	#tempname blogins
			user = args[4].lower()
			self.callEvent("onMemberJoin", user)

	@asyncio.coroutine
	def _recv_bw(self, args):
		'''Banned words'''
		self._bannedWords = args[0].split("%2C")

	@asyncio.coroutine
	def _recv_n(self, args):
		'''Number of users, in base 16'''
		self._usercount = int(args[0],16)
		self.callEvent("onUsercount")
		
	@asyncio.coroutine
	def _recv_b(self, args):
		'''Command fired on message received'''
		post = _formatMsg(args, 'b')
		if post.time > self._last:
			self._last = post.time
		self._messages[post.pnum] = post

	@asyncio.coroutine
	def _recv_u(self,args):
		'''Command fired on update message'''
		post = self._messages.get(args[0])
		if post:
			del self._messages[args[0]]
			post.msgid = args[1]
			self.callEvent("onMessage", post)
		else:
			self.callEvent("onDroppedMessage", args)

	@asyncio.coroutine
	def _recv_i(self,args):
		'''Command fired on historical message'''
		post = _formatMsg(args, 'i')
		if post.time > self._last:
			self._last = post.time
		self._history.append(post)

	@asyncio.coroutine
	def _recv_gotmore(self, args):
		'''Command fired on finished history get'''
		self.callEvent("onHistoryDone", list(self._history))
		self._history.clear()
		self._timesGot += 1

	@asyncio.coroutine
	def _recv_show_fw(self, args):
		'''Command fired on flood warning'''
		self.callEvent("onFloodWarning")

	@asyncio.coroutine
	def _recv_show_tb(self, args):
		'''Command fired on flood ban'''
		self.callEvent("onFloodBan",int(args[0]))

	@asyncio.coroutine
	def _recv_tb(self, args):
		'''Command fired on flood ban reminder'''
		self.callEvent("onFloodBanRepeat",int(args[0]))

	@asyncio.coroutine
	def _recv_blocklist(self, args):
		'''Command fired on list of banned users'''
		self._banlist.clear()
		sections = ':'.join(args).split(';')
		for section in sections:
			params = section.split(':')
			if len(params) != 5: continue
			if params[2] == "": continue
			self._banlist.append((
				params[0], #unid
				params[1], #ip
				params[2], #target
				float(params[3]), #time
				params[4] #src
			))
		self.callEvent("onBanlistUpdate")

	@asyncio.coroutine
	def _recv_blocked(self, args):
		'''Command fired on user banned'''
		if args[2] == "": return
		target = args[2]
		user = args[3]
		self._banlist.append((args[0], args[1], target, float(args[4]), user))
		self.callEvent("onBan", user, target)
		self.requestBanlist()

	@asyncio.coroutine
	def _recv_unblocked(self, args):
		'''Command fired on user unbanned'''
		if args[2] == "": return
		target = args[2]
		user = args[3]
		self.callEvent("onUnban", user, target)
		self.requestBanlist()

	@asyncio.coroutine
	def _recv_mods(self, args):
		'''Command fired on mod change'''
		mods = set(map(lambda x: x.lower(), args))
		premods = self._mods
		for user in mods - premods: #modded
			self._mods.add(user)
			self.callEvent("onModAdd", user)
		for user in premods - mods: #demodded
			self._mods.remove(user)
			self.callEvent("onModRemove", user)
		self.callEvent("onModChange")

	@asyncio.coroutine
	def _recv_delete(self, args):
		'''Command fired on message delete'''
		self.callEvent("onMessageDelete", args[0])

	@asyncio.coroutine
	def _recv_deleteall(self, args):
		'''Command fired on message delete (multiple)'''
		for msgid in args:
			self.callEvent("onMessageDelete", msgid)
	#--------------------------------------------------------------------------

	@asyncio.coroutine
	def sendPost(self, post, channel = 0, html = False):
		'''Send a post to the group'''
		channel = (((channel&2)<<2 | (channel&1))<<8)
		if not html:
			#replace HTML equivalents
			for i,j in reversed(HTML_CODES):
				post = post.replace(j,i)
			post = post.replace('\n',"<br/>")
		if len(post) > self._maxLength:
			if self._tooBigMessage == BigMessage_Cut:
				yield from self.sendPost(post[:self._maxLength], channel = channel, html = True)
			elif self._tooBigMessage == BigMessage_Multiple:
				while len(post) > 0:
					sect = post[:self._maxLength]
					post = post[self._maxLength:]
					yield from self.sendPost(sect, channel, html = True)
			return
		self.sendCommand("bm","meme",str(channel)
			,"<n{}/><f x{:02d}{}=\"{}\">{}".format(self.nColor, self.fSize
			, self.fColor, self.fFace, post))

	def getMore(self, amt = 20):
		'''Get more historical messages'''
		self.sendCommand("get_more",str(amt),str(self._timesGot))

	def flag(self, message):
		'''
		Flag a message
		Argument `message` must be a `Post` object (generated by _formatMsg)
		'''
		self.sendCommand("g_flag", message.pnum)

	def delete(self, message):
		'''
		Delete a message (Mod)
		Argument `message` must be a `Post` object (generated by _formatMsg)
		'''
		if self.getLevel(self.user) > 0:
			self.sendCommand("delmsg", message.pnum)

	def clearUser(self, message):
		'''
		Delete all of a user's messages (Mod)
		Argument `message` must be a `Post` object (generated by _formatMsg)
		'''
		if self.getLevel(self.user) > 0:
			self.sendCommand("delallmsg", message.unid)
	
	def ban(self, message):
		'''
		Ban a user from a message (Mod)
		Argument `message` must be a `Post` object (generated by _formatMsg)
		'''
		if self.getLevel(self.user) > 0:
			self.sendCommand("block", message.user, message.ip, message.unid)
  
	def unban(self, user):
		'''
		Unban a user by name (Mod)
		Argument `user` must be a string
		'''
		rec = None
		for record in self._banlist:
			if record[2] == user:
				rec = record
				break
		if rec:
			self.sendCommand("removeblock", rec[0], rec[1], rec[2])
			return True
		else:
			return False

	def requestBanlist(self):
		'''Request updated banlist (Mod)'''
		self.sendCommand("blocklist", "block", "", "next", "500")

	def addMod(self, user):
		'''Add moderator (Owner)'''
		if self.getLevel(self._manager.username) == 2:
			self.sendCommand("addmod", user)

	def removeMod(self, user):
		'''Remove moderator (Owner)'''
		if self.getLevel(self._manager.username) == 2:
			self.sendCommand("removemod", user)

	def clearall(self):
		'''Clear all messages (Owner)'''
		if self.getLevel(self.user) == 2:
			self.sendCommand("clearall")

	def getLevel(self, user):
		'''Get level of permissions in group'''
		if user == self._owner: return 2
		if user in self._mods: return 1
		return 0

class Manager:
	def __init__(self, username, password, loop=None):
		self.loop = asyncio.get_event_loop() if loop is None else loop
		self._groups = set()
		self.username = username
		self.password = password

	@asyncio.coroutine
	def joinGroup(self, groupName, port=443):
		'''Join group `groupName`'''
		groupName = groupName.lower()

		server = _Generate.serverNum(groupName)
		if server is None: raise Exception("Malformed room token: " + room)

		if groupName != self.username:
			ret = GroupProtocol(groupName, self)
			yield from self.loop.create_connection(lambda: ret,
				"s{}.chatango.com".format(server), port)
			self._groups.add(ret)
			return ret

	@asyncio.coroutine
	def leaveGroup(self, groupName):
		'''Leave group `groupName`'''
		if isinstance(groupName,GroupProtocol): groupName = groupName.name
		for group in self._groups:
			if group.name == groupName:
				group.disconnect()

	def uploadAvatar(self, path):
		'''Upload an avatar with path `path`'''
		extension = path[path.rfind('.')+1:].lower()
		if extension == "jpg": extension = "jpeg"
		elif extension not in ["png","jpeg"]:
			return False

		urllib.request.urlopen(_Multipart('http://chatango.com/updateprofile',
			data = {'u':		self.username
				,'p':			self.password
				,"auth":		"pwd"
				,"arch":		"h5"
				,"src":			"group"
				,"action":		"fullpic"
				,"Filedata":	("image/%s" % extension, open(path,"br"))
			}))
		return True

	def pmAuth(self):
		'''Request auth cookie for PMs'''
		login = urllib.request.urlopen("http://chatango.com/login",
			  data = urllib.parse.urlencode({
				 "user_id":		self.username
				,"password":	self.password
				,"storecookie":	"on"
				,"checkerrors":	"yes" 
				}).encode())
		for i in login.headers.get_all("Set-Cookie"):
			search = re.search("auth.chatango.com=(.*?);", i)
			if search:
				return search.group(1)
