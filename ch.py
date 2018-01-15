#!/usr/bin/env python3
#ch.py
'''
An asyncio rewrite of the chatango library based on cellsheet's chlib.py and
lumirayz's ch.py. Event based library for chatango rooms. Features channel 
support and fetching history messages among all other functionalities provided
by those versions.
'''
#TODO	better modtools
#TODO	property docstrings
#TODO	I have no idea why, but PMs are failing in all implementations.
#		Attempts to connect via websockets in a browser console also failed
#		abandoning attempts to fix for a while
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
XML_TAG_RE = re.compile("(</?(.*?)/?>)")
THUMBNAIL_FIX_RE = re.compile(r"(https?://ust\.chatango\.com/.+?/)t(_\d+.\w+)")

weights = [['5', 75], ['6', 75], ['7', 75], ['8', 75], ['16', 75], ['17', 75], ['18', 75], ['9', 95], ['11', 95], ['12', 95], ['13', 95], ['14', 95], ['15', 95], ['19', 110], ['23', 110], ['24', 110], ['25', 110], ['26', 110], ['28', 104], ['29', 104], ['30', 104], ['31', 104], ['32', 104], ['33', 104], ['35', 101], ['36', 101], ['37', 101], ['38', 101], ['39', 101], ['40', 101], ['41', 101], ['42', 101], ['43', 101], ['44', 101], ['45', 101], ['46', 101], ['47', 101], ['48', 101], ['49', 101], ['50', 101], ['52', 110], ['53', 110], ['55', 110], ['57', 110], ['58', 110], ['59', 110], ['60', 110], ['61', 110], ['62', 110], ['63', 110], ['64', 110], ['65', 110], ['66', 110], ['68', 95], ['71', 116], ['72', 116], ['73', 116], ['74', 116], ['75', 116], ['76', 116], ['77', 116], ['78', 116], ['79', 116], ['80', 116], ['81', 116], ['82', 116], ['83', 116], ['84', 116]]
specials = {"de-livechat": 5, "ver-anime": 8, "watch-dragonball": 8, "narutowire": 10, "dbzepisodeorg": 10, "animelinkz": 20, "kiiiikiii": 21, "soccerjumbo": 21, "vipstand": 21, "cricket365live": 21, "pokemonepisodeorg": 22, "watchanimeonn": 22, "leeplarp": 27, "animeultimacom": 34, "rgsmotrisport": 51, "cricvid-hitcric-": 51, "tvtvanimefreak": 54, "stream2watch3": 56, "mitvcanal": 56, "sport24lt": 56, "ttvsports": 56, "eafangames": 56, "myfoxdfw": 67, "peliculas-flv": 69, "narutochatt": 70}

HTML_CODES = \
	[("&#39;","'")
	,("&gt;",'>')
	,("&lt;",'<')
	,("&quot;",'"')
	,("&apos;","'")
	,("&amp;",'&')
]
def formatRaw(raw):
	'''
	Format a raw html string into one with newlines 
	instead of <br>s and all tags formatted out
	'''
	if len(raw) == 0: return raw
	#replace <br>s with actual line breaks
	#otherwise, remove html
	acc = 0
	for i in XML_TAG_RE.finditer(raw):
		start,end = i.span(1)
		rep = ""
		if i.group(2) == "br":
			rep = '\n'
		raw = raw[:start-acc] + rep + raw[end-acc:]
		acc += end-start - len(rep)
	raw.replace("&nbsp;",' ')
	for i,j in HTML_CODES:
		raw = raw.replace(i,j)
	#remove trailing \n's
	while len(raw) and raw[-1] == "\n":
		raw = raw[:-1]
	#thumbnail fix in chatango
	return raw

class Post:
	'''
	Objects that represent messages in chatango
	Post objects have support for channels and formatting parsing
	'''
	def __init__(self, raw, msgtype):
		self.time = float(raw[0])
		self.uid = raw[3]
		self.unid = raw[4]
		self.pnum = raw[5] if msgtype == 0 else None
		self.msgid = raw[5] if msgtype == 1 else None
		self.ip = raw[6]
		almostCooked = formatRaw(':'.join(raw[9:]))
		self.post = THUMBNAIL_FIX_RE.subn(r"\1l\2",almostCooked)[0]

		tag = POST_TAG_RE.search(raw[9])
		if tag:
			self.nColor = tag.group(2) or ''
			sizeAndColor = tag.group(4)
			if sizeAndColor:
				if len(sizeAndColor) % 3 == 2:	#color only
					self.fSize = int(sizeAndColor[:2])
					self.fColor = sizeAndColor[2:]
				else:
					self.fColor = sizeAndColor
					self.fSize = 12
			else:
				self.fColor = ''
				self.fSize = 12
			self.fFace = int(tag.group(5) or 0)
		#user parsing
		user = raw[1].lower()
		if not user:
			if raw[2] != "":
				user = '#' + raw[2].lower()
			else:
				user = "!anon" + _Generate.aid(self.nColor, self.uid)
			#nColor doesn't count for anons, because it changes their number
			self.nColor = ''

		self.user = user
		channel = (int(raw[7]) >> 8) & 31
		self.channel = channel&1|((channel&8)>>2)|((channel&16)>>3)

class _Generate:
	'''Generator functions for ids and server numbers'''
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

class _Multipart(urllib.request.Request):
	'''Simplified version of requests.post for multipart/form-data'''
	#code adapted from http://code.activestate.com/recipes/146306/
	MULTI_BOUNDARY = '---------------iM-in-Ur-pr07oc01'
	DISPOSITION = "Content-Disposition: form-data; name=\"%s\""

	def __init__(self, url, data, headers = {}):
		multiform = []
		for k,v in data.items():
			multiform.append("--" + self.MULTI_BOUNDARY) #add boundary
			data = v
			#the next part can have a (mime type, file) tuple
			if isinstance(v,(tuple, list)):
				if len(v) != 2:
					raise ValueError("improper multipart file tuple formatting")
				try:
					#try to read the file first
					data = v[1].read()
					v[1].close()
					#then set the filename to filename
					multiform.append((self.DISPOSITION % k) + \
						"; filename=\"%s\"" % os.path.basename(v[1].name))
					multiform.append("Content-Type: %s" % v[0])
				except AttributeError as ae:
					raise ValueError("expected file-like object") from ae
			else:
				#no mime type supplied
				multiform.append(self.DISPOSITION % k)
			multiform.append("")
			multiform.append(data)
		multiform.append("--" + self.MULTI_BOUNDARY + "--")
		#encode multiform
		request_body = (b"\r\n").join([isinstance(i,bytes) and i or i.encode() \
			for i in multiform])
		
		headers.update(	{"content-length":	str(len(request_body))
						,"content-type":	"multipart/form-data; boundary=%s"%\
							self.MULTI_BOUNDARY})

		super(_Multipart, self).__init__(url, data = request_body, headers = headers)

class ChatangoProtocol(asyncio.Protocol):
	'''Virtual class interpreting chatango's protocol'''
	_pingDelay = 15
	def __init__(self, manager, storage, loop=None):
		self._loop = manager.loop if loop is None else loop
		self._storage = storage
		self._manager = manager
		self._pingTask = None
		#socket stuff
		self._transport = None
		self.connected = False
		self._rbuff = b""
		#user id
		self._uid = _Generate.uid()

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
				#create a task for the recv event
				receive = getattr(self, "_recv_"+args[0])
				self._loop.create_task(receive(args[1:]))
			except AttributeError: pass
		self._rbuff = commands[-1]

	def connection_lost(self, exc):
		'''Cancel the ping task and fire onConnectionError'''
		if self._pingTask:
			self._loop.call_soon(self._pingTask.cancel)
		if self.connected: #connection lost if the transport closes abruptly
			self.callEvent("onConnectionError",exc)
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
			self._loop.create_task(event(self._storage, *args, **kw))
		except AttributeError: pass

	@asyncio.coroutine
	def disconnect(self):
		'''Safely close the transport. Prevents firing onConnectionError 'lost' '''
		if self._transport:
			self._transport.close()
		#cancel the ping task now
		if self._pingTask:
			self._pingTask.cancel()
			self._pingTask = None
		self.connected = False

	@asyncio.coroutine
	def ping(self):
		'''Send a ping to keep the transport alive'''
		while True:
			self.sendCommand("")
			yield from asyncio.sleep(self._pingDelay)

	@asyncio.coroutine
	def _recv_premium(self, args):
		'''Receive premium command. Called for both PM and Group'''
		#TODO write setBgMode and setRecordingMode
		if float(args[1]) > self._loop.time():
			self._storage._premium = True
			if self._storage._messageBackground: self.setBgMode(1)
			if self._storage._messageRecord: self.setRecordingMode(1)
		else:
			self._storage._premium = False

class GroupProtocol(ChatangoProtocol):
	'''Protocol interpreter for Chatango group commands'''
	def __init__(self, room, manager, loop=None):
		super(GroupProtocol,self).__init__(manager,Group(self,room),loop=loop)
		#intermediate message stuff and aux data for commands
		self._messages = {}
		self._history = []
		self._last = 0

	def connection_made(self, transport):
		'''Begins communication with the server and connects to the room'''
		#if i cared, i'd put this property-setting in a super method
		self._transport = transport
		self.connected = True
		self.sendCommand("bauth", self._storage._name, self._uid, self._manager.username,
			self._manager.password, firstcmd = True)

	#--------------------------------------------------------------------------
	@asyncio.coroutine
	def _recv_ok(self, args):
		'''Acknowledgement from server that login succeeded'''
		if args[2] == 'C' and (not self._manager.password) and (not self._manager.username):
			self._storage._anon = "!anon" + _Generate.aid(args[4], args[1])
			self._storage._nColor = "CCC"
		elif args[2] == 'C' and (not self._manager.password):
			self.sendCommand("blogin", self._manager.username)
		elif args[2] != 'M': #unsuccesful login
			self.callEvent("onLoginFail")
			yield from self.disconnect()
			return
		#shouldn't be necessary, but if the room assigns us a new id
		self._uid = args[1]
		self._storage._owner = args[0]
		self._storage._mods = set(mod.split(',')[0].lower()
			for mod in args[6].split(';'))
		#create a ping
		self._pingTask = self._loop.create_task(self.ping())

	@asyncio.coroutine
	def _recv_denied(self, args):
		'''Acknowledgement that login was denied'''
		self.callEvent("onDenied")
		yield from self.disconnect()
	
	@asyncio.coroutine
	def _recv_inited(self, args):
		'''Room inited, after recent messages have sent'''
		#TODO weed out null commands
		self.sendCommand("gparticipants")	#open up feed for members joining/leaving
		self.sendCommand("getpremium", '1')	#try to turn on premium features
		self.sendCommand("getbannedwords")	#what it says on the tin
		self.sendCommand("getratelimit")	#i dunno
		self.callEvent("onConnect")
		self.callEvent("onHistoryDone", list(self._history)) #clone history
		self._history.clear()

	@asyncio.coroutine
	def _recv_gparticipants(self, args):
		'''Command that contains information of current room members'''
		#gparticipants splits people by ;
		people = ':'.join(args[1:]).split(';')
		#room is empty except anons
		if people != ['']:
			for person in people:
				person = person.split(':')
				if person[3] != "None" and person[4] == "None":
					self._storage._users.append(person[3].lower())
		self.callEvent("onParticipants")

	@asyncio.coroutine
	def _recv_participant(self, args):
		'''New member joined or left'''
		bit = args[0]
		if bit == '0':	#left
			user = args[3].lower()
			if args[3] != "None" and user in self._storage._users:
				self._storage._users.remove(user)
				self.callEvent("onMemberLeave", user)
			else:
				self.callEvent("onMemberLeave", "anon")
		elif bit == '1':	#joined
			user = args[3].lower()
			if args[3] != "None":
				self._storage._users.append(user)
				self.callEvent("onMemberJoin", user)
			else:
				self.callEvent("onMemberJoin", "anon")
		elif bit == '2':	#tempname blogins
			user = args[4].lower()
			self.callEvent("onMemberJoin", user)

	@asyncio.coroutine
	def _recv_bw(self, args):
		'''Banned words'''
		self._storage._bannedWords = args[0].split("%2C")

	@asyncio.coroutine
	def _recv_n(self, args):
		'''Number of users, in base 16'''
		self._storage._usercount = int(args[0],16)
		self.callEvent("onUsercount")
		
	@asyncio.coroutine
	def _recv_b(self, args):
		'''Message received'''
		post = Post(args, 0)
		if post.time > self._last:
			self._last = post.time
		self._messages[post.pnum] = post

	@asyncio.coroutine
	def _recv_u(self,args):
		'''Message updated'''
		post = self._messages.get(args[0])
		if post:
			del self._messages[args[0]]
			post.msgid = args[1]
			self.callEvent("onMessage", post)
		else:
			self.callEvent("onDroppedMessage", args)

	@asyncio.coroutine
	def _recv_i(self,args):
		'''Historical message'''
		post = Post(args, 1)
		if post.time > self._last:
			self._last = post.time
		self._history.append(post)

	@asyncio.coroutine
	def _recv_gotmore(self, args):
		'''Received all historical messages'''
		self.callEvent("onHistoryDone", list(self._history))
		self._history.clear()
		self._storage._timesGot += 1

	@asyncio.coroutine
	def _recv_show_fw(self, args):
		'''Flood warning'''
		self.callEvent("onFloodWarning")

	@asyncio.coroutine
	def _recv_show_tb(self, args):
		'''Flood ban'''
		self.callEvent("onFloodBan",int(args[0]))

	@asyncio.coroutine
	def _recv_tb(self, args):
		'''Flood ban reminder'''
		self.callEvent("onFloodBanRepeat",int(args[0]))

	@asyncio.coroutine
	def _recv_blocklist(self, args):
		'''Received list of banned users'''
		self._storage._banlist.clear()
		sections = ':'.join(args).split(';')
		for section in sections:
			params = section.split(':')
			if len(params) != 5: continue
			if params[2] == "": continue
			self._storage._banlist.append((
				params[0]	#unid
				,params[1]	#ip
				,params[2]	#target
				,float(params[3]) #time
				,params[4]	#src
			))
		self.callEvent("onBanlistUpdate")

	@asyncio.coroutine
	def _recv_blocked(self, args):
		'''User banned'''
		if args[2] == "": return
		target = args[2]
		user = args[3]
		self._storage._banlist.append((args[0], args[1], target, float(args[4]), user))
		self.callEvent("onBan", user, target)
		self.requestBanlist()

	@asyncio.coroutine
	def _recv_unblocked(self, args):
		'''User unbanned'''
		if args[2] == "": return
		target = args[2]
		user = args[3]
		self.callEvent("onUnban", user, target)
		self.requestBanlist()

	@asyncio.coroutine
	def _recv_mods(self, args):
		'''Moderators changed'''
		mods = set(map(lambda x: x.lower(), args))
		premods = self._storage._mods
		for user in mods - premods: #modded
			self._storage._mods.add(user)
			self.callEvent("onModAdd", user)
		for user in premods - mods: #demodded
			self._storage._mods.remove(user)
			self.callEvent("onModRemove", user)
		self.callEvent("onModChange")

	@asyncio.coroutine
	def _recv_delete(self, args):
		'''Message deleted'''
		self.callEvent("onMessageDelete", args[0])

	@asyncio.coroutine
	def _recv_deleteall(self, args):
		'''Message delete (multiple)'''
		for msgid in args:
			self.callEvent("onMessageDelete", msgid)
	#--------------------------------------------------------------------------
	def requestBanlist(self):
		'''Request updated banlist (Mod)'''
		self.sendCommand("blocklist", "block", "", "next", "500")

class Connection:
	'''Virtual class for storing responses from protocols'''
	def __init__(self, protocol):
		self._protocol = protocol

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
		

class Group(Connection):
	'''Class for high-level group communication and storing group information'''
	_maxLength = 2000
	def __init__(self,protocol,room):
		super(Group,self).__init__(protocol)
		#user information
		self._name = room
		self._owner = None
		self._mods = set()
		self._bannedWords = []
		self._banlist = []
		self._users = []
		self._userSessions = {}
		self._usercount = 0

		self._timesGot = 0

		#########################################
		#	Properties
		#########################################

	username  = property(lambda self: self._anon or self._protocol._manager.username)
	name      = property(lambda self: self._name)
	owner     = property(lambda self: self._owner)
	modlist   = property(lambda self: set(self._mods))		#cloned set
	userlist  = property(lambda self: list(self._users))	#cloned list
	usercount = property(lambda self: self._usercount)
	banlist   = property(lambda self: [banned[2] for banned in self._banlist])	#by name; cloned
	last      = property(lambda self: self._protocol._last) #this is nice for the user to access

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
		self._protocol.sendCommand("bm","meme",str(channel)
			,"<n{}/><f x{:02d}{}=\"{}\">{}".format(self.nColor, self.fSize
			, self.fColor, self.fFace, post))

	def getMore(self, amt = 20):
		'''Get more historical messages'''
		self._protocol.sendCommand("get_more",str(amt),str(self._timesGot))

	def flag(self, message):
		'''
		Flag a message
		Argument `message` must be a `Post` object
		'''
		self._protocol.sendCommand("g_flag", message.msgid)

	def delete(self, message):
		'''
		Delete a message (Mod)
		Argument `message` must be a `Post` object
		'''
		if self.getLevel(self.username) > 0:
			self._protocol.sendCommand("delmsg", message.msgid)

	def clearUser(self, message):
		'''
		Delete all of a user's messages (Mod)
		Argument `message` must be a `Post` object
		'''
		if self.getLevel(self.username) > 0:
			self._protocol.sendCommand("delallmsg", message.unid)

	def ban(self, message):
		'''
		Ban a user from a message (Mod)
		Argument `message` must be a `Post` object
		'''
		if self.getLevel(self.username) > 0:
			self._protocol.sendCommand("block", message.user, message.ip, message.unid)
  
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
			self._protocol.sendCommand("removeblock", rec[0], rec[1], rec[2])
			return True
		else:
			return False

	def addMod(self, user):
		'''Add moderator (Owner)'''
		if self.getLevel(self.protocol._manager.username) == 2:
			self._protocol.sendCommand("addmod", user)

	def removeMod(self, user):
		'''Remove moderator (Owner)'''
		if self.getLevel(self.protocol._manager.username) == 2:
			self._protocol.sendCommand("removemod", user)

	def clearall(self):
		'''Clear all messages (Owner)'''
		if self.getLevel(self.username) == 2:
			self._protocol.sendCommand("clearall")

	def getLevel(self, user):
		'''Get level of permissions in group'''
		if user == self._owner: return 2
		if user in self._mods: return 1
		return 0
		

class Manager:
	'''
	Factory that creates and manages connections to chatango.
	This class also propogates all events from groups
	'''
	def __init__(self, username, password, loop=None):
		self.loop = asyncio.get_event_loop() if loop is None else loop
		self._groups = []
		self.username = username
		self.password = password

	def __del__(self):
		if self.loop.is_closed(): return
		for i in self._groups:
			#disconnect (and cancel all ping tasks)
			self.loop.run_until_complete(i._protocol.disconnect())

	@asyncio.coroutine
	def joinGroup(self, groupName, port=443):
		'''Join group `groupName`'''
		groupName = groupName.lower()

		server = _Generate.serverNum(groupName)
		if server is None: raise Exception("Malformed room token: " + room)

		#already joined group
		if groupName != self.username and groupName not in self._groups:
			ret = GroupProtocol(groupName, self)
			yield from self.loop.create_connection(lambda: ret,
				"s{}.chatango.com".format(server), port)
			self._groups.append(ret._storage)
			return ret._storage
		else:
			raise Exception("Attempted to join group multiple times")

	@asyncio.coroutine
	def leaveGroup(self, groupName):
		'''Leave group `groupName`'''
		if isinstance(groupName,Group): groupName = groupName.name
		find = -1
		for index,group in enumerate(self._groups):
			if group.name == groupName:
				yield from group._protocol.disconnect()
				find = index
		if find != -1:
			self._groups.pop(index)

	@asyncio.coroutine
	def leaveAll(self):
		'''Disconnect from all groups'''
		for group in self._groups:
			yield from group._protocol.disconnect()
		self._groups.clear()

	def uploadAvatar(self, location):
		'''Upload an avatar with path `location`'''
		extension = location[location.rfind('.')+1:].lower()
		if extension == "jpg": extension = "jpeg"
		elif extension not in ("png","jpeg"):
			return False

		urllib.request.urlopen(_Multipart('http://chatango.com/updateprofile',
			data = {'u':		self.username
				,'p':			self.password
				,"auth":		"pwd"
				,"arch":		"h5"
				,"src":			"group"
				,"action":		"fullpic"
				,"Filedata":	("image/%s" % extension, open(location,"br"))
			}))
		return True
