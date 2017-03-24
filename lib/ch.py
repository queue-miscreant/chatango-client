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

################################
#Python Imports
################################
import os
import time
import random
import re
import socket
import select
import urllib.request

BigMessage_Cut = 0
BigMessage_Multiple = 1

weights = [['5', 75], ['6', 75], ['7', 75], ['8', 75], ['16', 75], ['17', 75], ['18', 75], ['9', 95], ['11', 95], ['12', 95], ['13', 95], ['14', 95], ['15', 95], ['19', 110], ['23', 110], ['24', 110], ['25', 110], ['26', 110], ['28', 104], ['29', 104], ['30', 104], ['31', 104], ['32', 104], ['33', 104], ['35', 101], ['36', 101], ['37', 101], ['38', 101], ['39', 101], ['40', 101], ['41', 101], ['42', 101], ['43', 101], ['44', 101], ['45', 101], ['46', 101], ['47', 101], ['48', 101], ['49', 101], ['50', 101], ['52', 110], ['53', 110], ['55', 110], ['57', 110], ['58', 110], ['59', 110], ['60', 110], ['61', 110], ['62', 110], ['63', 110], ['64', 110], ['65', 110], ['66', 110], ['68', 95], ['71', 116], ['72', 116], ['73', 116], ['74', 116], ['75', 116], ['76', 116], ['77', 116], ['78', 116], ['79', 116], ['80', 116], ['81', 116], ['82', 116], ['83', 116], ['84', 116]]
specials = {"de-livechat": 5, "ver-anime": 8, "watch-dragonball": 8, "narutowire": 10, "dbzepisodeorg": 10, "animelinkz": 20, "kiiiikiii": 21, "soccerjumbo": 21, "vipstand": 21, "cricket365live": 21, "pokemonepisodeorg": 22, "watchanimeonn": 22, "leeplarp": 27, "animeultimacom": 34, "rgsmotrisport": 51, "cricvid-hitcric-": 51, "tvtvanimefreak": 54, "stream2watch3": 56, "mitvcanal": 56, "sport24lt": 56, "ttvsports": 56, "eafangames": 56, "myfoxdfw": 67, "peliculas-flv": 69, "narutochatt": 70}

AUTH_RE = re.compile("auth\.chatango\.com ?= ?(.*?);")
POST_TAG_RE = re.compile("(<n([a-fA-F0-9]{1,6})\/>)?(<f x([0-9a-fA-F]{2,8})=\"([0-9a-zA-Z]*)\">)?")
XML_TAG_RE = re.compile("(<.*?>)")
THUMBNAIL_FIX_RE = re.compile(r"(https?://ust.chatango.com/.+?/)t(_\d+.\w+)")

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
		num1 = 1000 if len(group) < 7 else max(int(group[6:9], 36), 1000)
		num2 = (int(group[:5],36) % num1) / num1
		for i, v in weights:
			gw += v / wt
			if gw >= num2:
				return i
		return None

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
	channel = (int(raw[7]) >> 8) & 15		#TODO mod channel on 2**15
	post.channel = channel&1|(channel&8)>>2

	return post

class Task:
	'''
	An object that contains a function. Executed every Manager tick,
	where ticks occur every time socket io is performed (default ~.2 seconds)
	'''
	def __init__(self, manager, timeout, interval, func, *args, **kwargs):
		self._manager = manager
		self._timeout = timeout
		self.target = time.time() + timeout
		self._isInterval = interval
		self._func = func
		self._args = args
		self._kwargs = kwargs
	
	def __call__(self):
		self._func(*self._args,**self._kwargs)
		if self._isInterval:
			self.target = time.time() + self._timeout
		else:
			self.cancel()

	def __bool__(self):
		return self in self._manager.tasks

	@classmethod
	def addInterval(cons, manager, timeout, func, *args, **kwargs):
		'''
		Task that comes pre-added to the manager. Set to recur every `timeout`
		number of seconds
		'''
		ret = cons(manager, timeout, True, func, *args, **kwargs)
		ret.add()
		return ret

	@classmethod
	def addTimeout(cons, manager, timeout, func, *args, **kwargs):
		'''
		Task that comes pre-added to the manager. Set to occur once, after
		`timeout` number of seconds
		'''
		ret = cons(manager, timeout, False, func, *args, **kwargs)
		ret.add()
		return ret

	def cancel(self):
		'''Cancel a task, stopping it from being called'''
		self._manager.tasks.remove(self)
	
	def add(self):
		'''Add a task to the manager, which will call it when necessary'''
		self._manager.tasks.add(self)

class _Connection:
	'''A virtual connection object to chatango. Superclass to PM and Groups'''
	_maxLength = 2700
	_messageBackground = True
	_messageRecord = False
	_tooBigMessage = BigMessage_Multiple

	def __init__(self, manager, port):
		self._manager = manager
		#socket stuff
		self._port = port
		self.sock = None
		self._clearBuffers()

		#account information
		self._uid = _Generate.uid()
		self._anon = None
		self._premium = False
		#formatting
		self._nColor = None	
		self._fSize  = 11
		self._fColor = ""
		self._fFace  = 0

		self._pingTask = None
		self._canPing = False
		self.connected = False
		self._reconnecting = False

	####################################
	# Properties
	####################################
	def _setNameColor(self,nColor):
		if not self._anon: self._nColor = nColor
	def _setFontColor(self,fColor): self._fColor = fColor
	def _setFontSize(self,fSize): 	self._fSize = min(22,max(9,fSize))
	def _setFontFace(self,fFace): 	self._fFace = fFace
	def _getNameColor(self): 		return self._nColor
	def _getFontColor(self): 		return self._fColor
	def _getFontSize(self): 		return self._fSize
	def _getFontFace(self): 		return self._fFace

	nColor = property(_getNameColor,_setNameColor)
	fColor = property(_getFontColor,_setFontColor)
	fSize  = property(_getFontSize,_setFontSize)
	fFace  = property(_getFontFace,_setFontFace)

	####################################
	# Util
	####################################
	def _clearBuffers(self):
		self.wbuff = b""
		self._rbuff = b""
		self._wbufflock = b""
		self._wlock = False

	def _lockWrite(self,lock):
		'''Lock/unlock writing buffer'''
		self._wlock = lock
		if not lock:
			self.wbuff += self._wbufflock
			self._wbufflock = b""

	def _write(self,data):
		'''Write to writing buffer'''
		if self._wlock:
			self._wbufflock += data
		else:
			self.wbuff += data
	
	def _connect(self):
		'''Virtual method to set up the socket and connecting to a server'''
		pass

	def _disconnect(self):
		'''Disconnect backend'''
		if not self._reconnecting: self.connected = False
		if self._pingTask:
			self._pingTask.cancel()
		if self.sock:
			self.sock.close()

	def disconnect(self):
		'''Disconnect and call event'''
		self._callEvent("onDisconnect")
		self._disconnect()

	def reconnect(self):
		'''Reconnect'''
		if self._reconnecting: return
		self._reconnecting = True
		if self.connected:
			self._disconnect()
		self._uid = _Generate.uid()
		self._connect()
		self._reconnecting = False

	def _sendCommand(self, *args, firstcmd = False):
		'''Send data to socket'''
		if firstcmd:
			self._write(bytes(':'.join(args)+'\x00', "utf-8"))
		else:
			self._write(bytes(':'.join(args)+"\r\n\x00", "utf-8"))

	def _callEvent(self, event, *args, **kw):
		'''Attempt to call manager's method'''
		try:
			getattr(self._manager, event)(self, *args, **kw)
		except AttributeError: pass

	def digest(self, data):
		'''Parse argument as data from the socket and call method'''
		self._rbuff += data
		commands = self._rbuff.split(b'\x00')
		for command in commands[:-1]:
			args = command.decode("utf_8").rstrip("\r\n").split(':')
			try:
				if command == b"":
					self._recv_ping()
				getattr(self, "_recv_"+args[0])(args[1:])
			except AttributeError: pass
		self._rbuff = commands[-1]
	
	def _recv_ping(self):
		'''Receive a ping'''
		self._canPing = True

	def _recv_premium(self, args):
		'''Receive premium command. Called for both PM and Group'''
		if float(args[1]) > time.time():
			self._premium = True
			if self._messageBackground: self.setBgMode(1)
			if self._messageRecord: self.setRecordingMode(1)
		else:
			self._premium = False

	def setBgMode(self, mode):
		'''Send msgbg command, turning background on or off'''
		self._sendCommand("msgbg", str(mode))
  
	def setRecordingMode(self, mode):
		'''Send msgmedia command, setting recording on or off'''
		self._sendCommand("msgmedia", str(mode))

	def ping(self):
		'''Send a ping, or fail and disconnect'''
		if self._canPing:
			self._canPing = False
			self._sendCommand("")
		else:
			self._disconnect()
			self._callEvent("onConnectionLost")

class Group(_Connection):
	'''_Connection subclass for typical chatango Groups'''

	def __init__(self, room, manager, port = None):
		super(Group,self).__init__(manager, port or 443)
		self._server = _Generate.serverNum(room)
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
		self._last = 0
		self._timesGot = 0

		if manager: self._connect()

	#########################################
	#	Properties
	#########################################

	def _getUsername(self):
		if self._anon: return self._anon
		else: return self._manager.username
	def _getName(self):			return self._name
	def _getOwner(self):		return self._owner
	def _getModlist(self):		return set(self._mods)							#cloned set
	def _getUserlist(self):		return list(self._users)						#cloned list
	def _getUsercount(self):	return self._usercount
	def _getBanlist(self):		return [banned[2] for banned in self._banlist]	#by name; cloned
	def _getLastMsgTime(self):	return self._last

	username  = property(_getUsername)
	name      = property(_getName)
	owner     = property(_getOwner)
	modlist   = property(_getModlist)
	userlist  = property(_getUserlist)
	usercount = property(_getUsercount)
	banlist   = property(_getBanlist)
	last      = property(_getLastMsgTime)

	def _connect(self):
		'''Connect to the server. Fires onConnectionLost when this fails'''
		self._clearBuffers()
		try:
			self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.sock.connect(("s{}.chatango.com".format(self._server), self._port))
			self.sock.setblocking(False)
		except socket.gaierror:
			return self._callEvent("onConnectionLost")
		#authenticate
		self._sendCommand("bauth", self._name, self._uid, self._manager.username, self._manager.password, firstcmd = True)

		self._lockWrite(True) #lock until inited
		self._pingTask = Task.addInterval(self._manager, self._manager._pingDelay, self.ping)
		self._canPing = True
		if not self._reconnecting: self.connected = True

	#########################################
	#	Received command backends
	#########################################

	def _recv_ok(self, args):
		'''Acknowledgement from server that login succeeded'''
		if args[2] == 'C' and (not self._manager.password) and (not self._manager.username):
			self._anon = "!anon" + _Generate.aid(args[4], args[1])
			self._nColor = "CCC"
		elif args[2] == 'C' and (not self._manager.password):
			self._sendCommand("blogin", self._manager.username)
		elif args[2] != 'M': #unsuccesful login
			self._callEvent("onLoginFail")
			self.disconnect()
			return
		self._owner = args[0]
		self._uid = args[1]	
		self._mods = set(mod.split(',')[0].lower() for mod in args[6].split(';'))

	def _recv_denied(self, args):
		'''Acknowledgement that login was denied'''
		self._disconnect()
		self._callEvent("onDenied")
	
	def _recv_inited(self, args):
		'''Command fired on room inited, after recent messages have sent'''
		#TODO weed out null commands
		self._sendCommand("gparticipants")
		self._sendCommand("getpremium", '1')
		self._sendCommand("getbannedwords")
		self._sendCommand("getratelimit")
		self._callEvent("onConnect")
		self._callEvent("onHistoryDone", self._history)
		self._history.clear()
		self._lockWrite(False)

	def _recv_gparticipants(self, args):
		'''Command that contains information of current room members'''
		#gparticipants splits people by ;
		people = ':'.join(args[1:]).split(';')
		for person in people:
			person = person.split(':')
			if person[3] != "None" and person[4] == "None":
				self._users.append(person[3].lower())
				self._userSessions[person[2]] = person[3].lower()
		self._callEvent("onParticipants")

	def _recv_participant(self, args):
		'''Command fired on new member join'''
		bit = args[0]
		if bit == '0':	#left
			user = args[3].lower()
			if args[3] != "None" and user in self._users:
				self._users.remove(user)
				self._callEvent("onMemberLeave", user)
			else:
				self._callEvent("onMemberLeave", "anon")
		elif bit == '1':	#joined
			user = args[3].lower()
			if args[3] != "None":
				self._users.append(user)
				self._callEvent("onMemberJoin", user)
			else:
				self._callEvent("onMemberJoin", "anon")
		elif bit == '2':	#tempname blogins
			user = args[4].lower()
			self._callEvent("onMemberJoin", user)

	def _recv_bw(self, args):
		'''Banned words'''
		self._bannedWords = args[0].split("%2C")

	def _recv_n(self, args):
		'''Number of users, in base 16'''
		self._usercount = int(args[0],16)
		self._callEvent("onUsercount")
		
	def _recv_b(self, args):
		'''Command fired on message received'''
		post = _formatMsg(args, 'b')
		if post.time > self._last:
			self._last = post.time
		self._messages[post.pnum] = post

	def _recv_u(self,args):
		'''Command fired on update message'''
		post = self._messages.get(args[0])
		if post:
			del self._messages[args[0]]
			post.msgid = args[1]
			self._callEvent("onMessage", post)
		else:
			self._callEvent("onDroppedMessage", args)

	def _recv_i(self,args):
		'''Command fired on historical message'''
		post = _formatMsg(args, 'i')
		if post.time > self._last:
			self._last = post.time
		self._history.append(post)

	def _recv_gotmore(self, args):
		'''Command fired on finished history get'''
		self._callEvent("onHistoryDone", self._history)
		self._history.clear()
		self._timesGot += 1

	def _recv_show_fw(self, args):
		'''Command fired on flood warning'''
		self._callEvent("onFloodWarning")
	
	def _recv_show_tb(self, args):
		'''Command fired on flood ban'''
		self._callEvent("onFloodBan",int(args[0]))
  
	def _recv_tb(self, args):
		'''Command fired on flood ban reminder'''
		self._callEvent("onFloodBanRepeat",int(args[0]))

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
		self._callEvent("onBanlistUpdate")

	def _recv_blocked(self, args):
		'''Command fired on user banned'''
		if args[2] == "": return
		target = args[2]
		user = args[3]
		self._banlist.append((args[0], args[1], target, float(args[4]), user))
		self._callEvent("onBan", user, target)
		self.requestBanlist()
  
	def _recv_unblocked(self, args):
		'''Command fired on user unbanned'''
		if args[2] == "": return
		target = args[2]
		user = args[3]
		self._callEvent("onUnban", user, target)
		self.requestBanlist()
  
	def _recv_mods(self, args):
		'''Command fired on mod change'''
		mods = set(map(lambda x: x.lower(), args))
		premods = self._mods
		for user in mods - premods: #modded
			self._mods.add(user)
			self._callEvent("onModAdd", user)
		for user in premods - mods: #demodded
			self._mods.remove(user)
			self._callEvent("onModRemove", user)
		self._callEvent("onModChange")

	def _recv_delete(self, args):
		'''Command fired on message delete'''
		self._callEvent("onMessageDelete", args[0])
  
	def _recv_deleteall(self, args):
		'''Command fired on message delete (multiple)'''
		for msgid in args:
			self._recv_delete([msgid])

	#########################################
	#	Command Frontends
	#########################################

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
				self.sendPost(post[:self._maxLength], channel = channel, html = True)
			elif self._tooBigMessage == BigMessage_Multiple:
				while len(post) > 0:
					sect = post[:self._maxLength]
					post = post[self._maxLength:]
					self.sendPost(sect, channel, html = True)
			return
		self._sendCommand("bm","meme",str(channel),"<n{}/><f x{:02d}{}=\"{}\">{}".format(self.nColor,
			self.fSize, self.fColor, self.fFace, post))

	def getMore(self, amt = 20):
		'''Get more historical messages'''
		self._sendCommand("get_more",str(amt),str(self._timesGot))

	def flag(self, message):
		'''
		Flag a message
		Argument `message` must be a `Post` object (generated by _formatMsg)
		'''
		self._sendCommand("g_flag", message.pnum)

	def delete(self, message):
		'''
		Delete a message (Mod)
		Argument `message` must be a `Post` object (generated by _formatMsg)
		'''
		if self.getLevel(self.user) > 0:
			self._sendCommand("delmsg", message.pnum)

	def clearUser(self, message):
		'''
		Delete all of a user's messages (Mod)
		Argument `message` must be a `Post` object (generated by _formatMsg)
		'''
		if self.getLevel(self.user) > 0:
			self._sendCommand("delallmsg", message.unid)
	
	def ban(self, message):
		'''
		Ban a user from a message (Mod)
		Argument `message` must be a `Post` object (generated by _formatMsg)
		'''
		if self.getLevel(self.user) > 0:
			self._sendCommand("block", message.user, message.ip, message.unid)
  
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
			self._sendCommand("removeblock", rec[0], rec[1], rec[2])
			return True
		else:
			return False

	def requestBanlist(self):
		'''Request updated banlist (Mod)'''
		self._sendCommand("blocklist", "block", "", "next", "500")

	def addMod(self, user):
		'''Add moderator (Owner)'''
		if self.getLevel(self._manager.username) == 2:
			self._sendCommand("addmod", user)

	def removeMod(self, user):
		'''Remove moderator (Owner)'''
		if self.getLevel(self._manager.username) == 2:
			self._sendCommand("removemod", user)

	def clearall(self):
		'''Clear all messages (Owner)'''
		if self.getLevel(self.user) == 2:
			self._sendCommand("clearall")

	def getLevel(self, user):
		'''Get level of permissions in group'''
		if user == self._owner: return 2
		if user in self._mods: return 1
		return 0

class PM(_Connection):
	_PMHost =  "c1.chatango.com"

	def __init__(self, manager, port = None):
		super(PM,self).__init__(manager, port or 8080)
		self._auid = None
		self._contacts = []
		self._blocklist = set()

		if manager: self._connect()

	#########################################
	#	Properties
	#########################################

	def _getContacts(self):		return list(self._contacts)			#cloned list
	def _getBlocked(self):		return set(self._blocklist)			#cloned set

	contacts  = property(_getContacts)
	blocklist = property(_getBlocked)

	def _connect(self):
		'''Connect to PM server'''
		self._clearBuffers()
		self._auid = self._manager.pmAuth()
		if self._auid == None:
			return self._callEvent("onLoginFail")
		try:
			self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.sock.connect((self._PMHost, self._port))
			self.sock.setblocking(False)
		except socket.gaierror:
			return self._callEvent("onConnectionLost")

		self._sendCommand("tlogin", self._auid, '2', self._uid, firstcmd = True)
		self._lockWrite(True)

		self._pingTask = Task.addInterval(self._manager, self._manager._pingDelay, self.ping)
		if not self._reconnecting: self.connected = True

	#########################################
	#	Received command backends
	#########################################

	def _recv_OK(self, args):
		'''Acknowledgement of PM login success'''
		self._lockWrite(False)
		self._sendCommand("wl")
		self._sendCommand("getblock")
		self._callEvent("onPMConnect")

	def _recv_DENIED(self, args):
		'''Acknowledgement of PM login failure'''
		self._disconnect()
		self._callEvent("onLoginFail")

	def _recv_wl(self,args):
		'''Command fired on friends list received'''
		for i in range(len(args)//4):
			user, last, online, idle  = args[i*4:i*4 + 4]
			contacts.add(user)
		self._callEvent("onPMContactList")

	def _recv_wladd(self, args):
		'''Command fired on friend added'''
		contacts.add(args[0])
		self._callEvent("onPMContactAdded", args[0])

	def _recv_wldelete(self, args):
		'''Command fired on friend deleted'''
		contacts.remove(args[0])
		self._callEvent("onPMContactRemoved",args[0])

	def _recv_msg(self, args):
		'''Command fired on PM received'''
		msg = formatRaw(':'.join(args[1:]))
		user = args[0]
		self._callEvent("onPM", user, msg)
	
	def _recv_msgoff(self, args):
		'''Command fired on offline PM received'''
		body = formatRaw(':'.join(args[1:]))
		user = args[0]
		self._callEvent("onPMOffline", user, body)

	def _recv_wlonline(self, args):
		'''Command fired on friend online'''
		self._callEvent("onPMContactOnline", args[0])
  
	def _recv_wloffline(self, args):
		'''Command fired on friend offline'''
		self._callEvent("onPMContactOffline", args[0])

	def _recv_block_list(self, args):
		'''Command fired block list received'''
		self._blocklist = set()
		for name in args:
			if name == "": continue
			self._blocklist.add(name)
		self._callEvent("onPMBlockList")

	def _recv_kickingoff(self, args):
		'''Command fired on disconnect'''
		self.disconnect()

	#########################################
	#	Command Frontends
	#########################################

	def sendPM(self, target, post, html = False):
		'''Send private message to the user with name `target`'''
		if not html:
			#replace HTML equivalents
			for i,j in reversed(HTML_CODES):
				post = post.replace(j,i)
			post = post.replace('\n',"<br/>")

		if len(post) > self._maxLength:
			if self._tooBigMessage == BigMessage_Cut:
				self.sendPM(target, post[:self._maxLength], html = html)
			elif self._tooBigMessage == BigMessage_Multiple:
				while len(post) > 0:
					sect = post[:self._maxLength]
					post = post[self._maxLength:]
					self.sendPM(target, sect, html = html)
			return
		#TODO colored PMs
#		self._sendCommand("msg", str(target), "<n{}/><f x{}{}=\"{}\">{}".format(self.nColor,
#			self.fSize, self.fColor, self.fFace, post))
		self._sendCommand("msg", str(target), post)

	def addContact(self, user):
		'''Add a friend'''
		if user not in self._contacts:
			self._sendCommand("wladd", user.name)
			self._contacts.add(user)
	
	def removeContact(self, user):
		'''Remove a friend'''
		if user in self._contacts:
			self._sendCommand("wldelete", user.name)
			self._contacts.remove(user)

	def block(self, user):
		'''Block a user'''
		if user not in self._blocklist:
			self._sendCommand("block", user.name)
			self._blocklist.remove(user)
			self._callEvent("onPMBlock", user)

	def unblock(self, user):
		'''Unblock a user'''
		if user in self._blocklist:
			self._sendCommand("unblock", user.name)
			self._blocklist.remove(user)
			self._callEvent("onPMUnblock", user)

class Manager:
	'''
	Class that manages multiple connections to chatango
	All methods of the form `on*` are virtual methods for event callbacks

	Event callbacks (except for onInit) have the same initial argument
	(other than self): `group` corresponds to a _Connection (Group or PM)
	object the event was called from.
	'''
	_socketTimer = .2
	_pingDelay = 15
	def __init__(self, username, password, pm = False):
		self.username = username
		self.password = password
		self.running = False
		self._groups = set()
		self.tasks = set()
		self.pm = None
		if pm:
			self.pm = PM(self)

	def main(self):
		'''Main function to read/write from all connected sockets'''
		self.onInit()
		self.running = True
		while self.running:
			socks = [group.sock for group in self._groups if group.connected]
			#don't write null strings (expends CPU)
			wsocks = [group.sock for group in self._groups if group.connected and group.wbuff]
			#select
			read, write, err = select.select(socks,wsocks,[],self._socketTimer)
			for sock in read:
				group = [i for i in self._groups if i.sock == sock][0]
				try:
					read = sock.recv(1024)
					group.digest(read)
				except socket.error:
					pass
			for sock in write:
				group = [i for i in self._groups if i.sock == sock][0]
				try:
					size = sock.send(group.wbuff)
					group.wbuff = group.wbuff[size:]
				except socket.error:
					pass
			self._tick()

	def stop(self):
		self.running = False
		for group in self._groups:
			group.disconnect()

	def _tick(self):
		'''Call all tasks if scheduled'''
		now = time.time()
		#need a copy to iterate over
		for task in list(self.tasks):
			if task.target <= now:
				task()

	def joinGroup(self, groupName):
		'''Join group `groupName`'''
		groupName = groupName.lower()
		if groupName != self.username:
			ret = Group(groupName,self)
			self._groups.add(ret)
			return ret

	def leaveGroup(self, groupName):
		'''Leave group `groupName`'''
		if isinstance(groupName,Group):
			for group in self._groups:
				if group == groupName:
					group.disconnect()
					return
			return
		groupName = groupName.lower()
		for group in self._groups:
			if group.name == groupName:
				group.disconnect()
				return

	def getGroup(self, groupName):
		'''Look for joined group `groupName`'''
		groupName = groupName.lower()
		for group in self._groups:
			if group.name == groupName:
				return group

	def uploadAvatar(self, path):
		'''Upload an avatar with path `path`'''
		extension = path[path.rfind('.')+1:].lower()
		if extension == "jpg": extension = "jpeg"
		elif extension not in ["png","jpeg"]:
			return False

		try:
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
		except FileNotFoundError:
			return False

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
	
	###################################
	#	Events
	###################################

	def onInit(self):
		'''Event called before main()'''
		pass

	def onDisconnect(self, group):
		'''Event called on group disconnect'''
		pass

	def onConnectionLost(self, group):
		'''Event called on group connection lost'''
		pass

	def onLoginFail(self, group):
		'''Event called on group login failure'''
		pass

	def onDenied(self, group):
		'''Event called on unsuccessful group join'''
		pass

	def onConnect(self, group):
		'''Event called on successful connection to group'''
		pass

	def onParticipants(self, group):
		'''Event called on group's members received'''
		pass

	def onMemberLeave(self, group, user):
		'''
		Event called on group member leave
		Arguments:
			str user:	the name of the user who left
		'''
		pass

	def onMemberJoin(self, group, user):
		'''
		Event called on group member join
		Arguments:
			str user:	the name of the user who joined
		'''
		pass

	def onUsercount(self, group):
		'''Event called on group member count'''
		pass

	def onMessage(self, group, post):
		'''
		Event called on message received
		Arguments:
			Post post:	a Post object generated by formatRaw()
		'''
		pass

	def onDroppedMessage(self, group, args):
		'''
		Event called on message dropped
		Arguments:
			args:	list of arguments received from the `u` command
		'''
		pass

	def onHistoryDone(self, group, history):
		'''
		Event called when historical messages have been received
		Arguments:
			[Post] history:	an array of Post objects generated by formatRaw(), 
							in descending time order
		'''
		pass

	def onFloodWarning(self, group):
		'''Event called on flood warning'''
		pass

	def onFloodBan(self, group, seconds):
		'''
		Event called on flood ban
		Arguments:
			int seconds:	the number of seconds before the ban is lifted
		'''
		pass

	def onFloodBanRepeat(self, group, seconds):
		'''
		Event called on flood reminder
		Arguments:
			int seconds:	the number of seconds before the ban is lifted
		'''
		pass

	def onBanlistUpdate(self, group):
		'''Event called on ban list update'''
		pass

	def onBan(self, group, user, target):
		'''
		Event called on user banned
		Arguments:
			str user:	the mod that banned the user
			str target:	the user that was banned
		'''
		pass

	def onUnban(self, group, user, target):
		'''
		Event called on user unbanned
		Arguments:
			str user:	the mod that unbanned the user
			str target:	the user that was unbanned
		'''
		pass

	def onModAdd(self, group, user):
		'''
		Event called on mod added
		Arguments:
			str user:	the mod that was added
		'''
		pass

	def onModRemove(self, group, user):
		'''
		Event called on mod removed
		Arguments:
			str user:	the mod that was removed
		'''
		pass

	def onModChange(self, group):
		'''Event called on modlist changed'''
		pass

	def onMessageDelete(self, group, msgid):
		'''
		Event called on message deleted
		Arguments:
			str msgid:	message ID of the message that was deleted	
		'''
		pass
	
	###################################
	#	PM Events
	###################################

	def onPMConnect(self, group):
		'''Event called on connect to PMs'''
		pass

	def onPMContactList(self, group):
		'''Event called on PM friends list received'''
		pass

	def onPM(self, group, user, message):
		'''
		Event called on PM received
		Arguments:
			str user:		the user that sent the message
			str message:	the message body, formatted with _formatRaw
		'''
		pass

	def onPMOffline(self, group, user, message):
		'''
		Event called on offline PM received
		Arguments:
			str user:		the user that sent the message
			str message:	the message body, formatted with _formatRaw
		'''
		pass

	def onPMContactOnline(self, group, user):
		'''
		Event called on PM contact online
		Arguments:
			str user:		the user that went online
		'''
		pass

	def onPMContactOffline(self, group, user):
		'''
		Event called on PM contact offline
		Arguments:
			str user:		the user that went offline
		'''
		pass

	def onPMContactAdd(self, group, user):
		'''
		Event called on PM contact add
		Arguments:
			str user:		the user that was added
		'''
		pass

	def onPMContactRemove(self, group, user):
		'''
		Event called on PM contact remove
		Arguments:
			str user:		the user that was removed
		'''
		pass

	def onPMBlock(self, group, user):
		'''
		Event called on PM user banned
		Arguments:
			str user:		the user that was banned
		'''
		pass

	def onPMUnblock(self, group, user):
		'''
		Event called on PM user unbanned
		Arguments:
			str user:		the user that was unbanned
		'''
		pass