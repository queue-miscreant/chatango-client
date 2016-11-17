#uid  :: user id
#unid :: unique user id, in base 64
#pid :: post id, after display
#pnum :: post number, before display
#TODO	are unids sent on participant calls?
#		for mods only?
#TODO	threaded start function

import socket
import random
import time
import threading
import re
import select

BigMessage_Cut = 0
BigMessage_Multiple = 1

weights = [['5', 75], ['6', 75], ['7', 75], ['8', 75], ['16', 75], ['17', 75], ['18', 75], ['9', 95], ['11', 95], ['12', 95], ['13', 95], ['14', 95], ['15', 95], ['19', 110], ['23', 110], ['24', 110], ['25', 110], ['26', 110], ['28', 104], ['29', 104], ['30', 104], ['31', 104], ['32', 104], ['33', 104], ['35', 101], ['36', 101], ['37', 101], ['38', 101], ['39', 101], ['40', 101], ['41', 101], ['42', 101], ['43', 101], ['44', 101], ['45', 101], ['46', 101], ['47', 101], ['48', 101], ['49', 101], ['50', 101], ['52', 110], ['53', 110], ['55', 110], ['57', 110], ['58', 110], ['59', 110], ['60', 110], ['61', 110], ['62', 110], ['63', 110], ['64', 110], ['65', 110], ['66', 110], ['68', 95], ['71', 116], ['72', 116], ['73', 116], ['74', 116], ['75', 116], ['76', 116], ['77', 116], ['78', 116], ['79', 116], ['80', 116], ['81', 116], ['82', 116], ['83', 116], ['84', 116]]
specials = {"de-livechat": 5, "ver-anime": 8, "watch-dragonball": 8, "narutowire": 10, "dbzepisodeorg": 10, "animelinkz": 20, "kiiiikiii": 21, "soccerjumbo": 21, "vipstand": 21, "cricket365live": 21, "pokemonepisodeorg": 22, "watchanimeonn": 22, "leeplarp": 27, "animeultimacom": 34, "rgsmotrisport": 51, "cricvid-hitcric-": 51, "tvtvanimefreak": 54, "stream2watch3": 56, "mitvcanal": 56, "sport24lt": 56, "ttvsports": 56, "eafangames": 56, "myfoxdfw": 67, "peliculas-flv": 69, "narutochatt": 70}

def getServer(group):
	'''Return server number'''
	if group in specials.keys():
		return specials[group]
	group = re.sub("-|_", "q", group)
	wt, gw = sum([n[1] for n in weights]), 0
	num1 = 1000 if len(group) < 7 else max(int(group[6:9], 36), 1000)
	num2 = (int(group[:5],36) % num1) / num1
	for i, v in weights:
		gw += v / wt
		if gw >= num2:
			return i
	return None

AUTH_RE = re.compile("auth\.chatango\.com ?= ?(.*?);")
POST_TAG_RE = re.compile("(<n([a-fA-F0-9]{1}|[a-fA-F0-9]{3}|[a-fA-F0-9]{4}|[a-fA-F0-9]{6})\/>)?(<f x([\d]{0}|[\d]{2})([0-9a-fA-F]{1}|[0-9a-fA-F]{3}|[0-9a-fA-F]{6})=\"([0-9a-zA-Z]*)\">)?")
XML_TAG_RE = re.compile("(<.*?>)")
THUMBNAIL_FIX_RE = re.compile(r"(https?://ust.chatango.com/.+?/)t(_\d+.\w+)")

HTML_CODES = [
	("&#39;","'"),
	("&gt;",">"),
	("&lt;","<"),
	("&quot;",'"'),
	("&apos;","'"),
	("&amp;",'&'),
]
def _formatRaw(raw):
	if len(raw) == 0: return raw
	#replace <br>s with actual line breaks
	#otherwise, remove html
	for i in XML_TAG_RE.findall(raw):
		raw = raw.replace(i,i == "<br/>" and "\n" or "")
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
	post = type("Post",(object,),
		{"time": float(raw[0])
		,"user": None
		,"pid":	None
		,"uid": raw[3]
		,"unid": raw[4]
		,"pnum": None
		,"ip": raw[6]
		,"channel": 0
		,"post": _formatRaw(":".join(raw[9:]))
		,"nColor": ""
		,"fSize": ""
		,"fFace": ""
		,"fColor": '0'})

	if bori == 'b':
		post.pnum = raw[5]
	elif bori == 'i':
		post.pid = raw[5]

	#user parsing
	user = raw[1].lower()
	if not user:
		if raw[2] != '':
			post.user = "#" + raw[2].lower()
		else:
			post.user = "!anon" + Generate.aid(nColor, raw[3])
	#
	channel = (int(raw[7]) >> 8) & 15		#TODO mod channel on 2**15
	post.channel = channel&1|(channel&8)>>2

	tag = POST_TAG_RE.search(raw[9])
	if tag:
		post.nColor = tag.group(2)
		post.fSize = tag.group(4)
		post.fColor = tag.group(5)
		post.fFace = tag.group(6)
	return post

class Task:
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

	def cancel(self):
		self._manager.tasks.remove(self)
	
	def add(self):
		self._manager.tasks.add(self)

class Generate:
	def uid():
		'''Generate unique ID'''
		return str(int(random.randrange(10 ** 15, (10 ** 16) - 1)))

	def aid(n, aid):
		'''Generate anon ID'''
		if n == None: n = "3452"
		try:
			return "".join(map(lambda i,v: str(int(i) + int(v))[-1],
						   str(n), aid))
		except:
			return "3452"

	def auth(pm):
		'''Generate auth token'''
		auth = urllib.request.urlopen("http://chatango.com/login",
			urllib.parse.urlencode({
			"user_id": pm.user,
			"password": pm.password,
			"storecookie": "on",
			"checkerrors": "yes" }).encode()
			).getheader("Set-Cookie")
		try:
			return re.search("auth.chatango.com=(.*?);", auth).group(1)
		except:
			return None
			
class Group:
	_maxLength = 2700
	_pingDelay = 20
	_messageBackground = True
	_messageRecord = False
	_tooBigMessage = BigMessage_Multiple

	def __init__(self, room, manager, port = None):
		self._manager = manager
		#socket stuff
		self._server = getServer(room)
		self._port = port or 443
		self.sock = None
		self.wbuff = b""
		self._rbuff = b""
		self._wbufflock = b""
		self._wlock = False
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
		#account information
		self._uid = Generate.uid()
		self._anon = None
		self._premium = False
		self._nColor = None	
		self._fSize  = 11
		self._fColor = ""
		self._fFace  = 0

		self._connected = False
		self._reconnecting = False
		if manager: self._connect()

	#
	# Properties
	#

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

	def _getName(self):			return self._name
	def _getOwner(self):		return self._owner
	def _getModlist(self):		return set(self._mods)							#cloned set
	def _getUserlist(self):		return list(self._users)						#cloned list
	def _getUsercount(self):	return self._usercount
	def _getBanlist(self):		return [banned[2] for banned in self._banlist]	#by name; cloned

	name      = property(_getName)
	owner     = property(_getOwner)
	modlist   = property(_getModlist)
	userlist  = property(_getUserlist)
	usercount = property(_getUsercount)
	banlist   = property(_getBanlist)

	def lock(self,lock):
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
		'''Connect to the server.'''
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.sock.connect(("s{}.chatango.com".format(self._server), self._port))
		self.sock.setblocking(False)
		self.wbuff = b""
		#authenticate
		if self._manager.username and self._manager.password:
			self._sendCommand("bauth", self._name, self._uid, self._manager.username, self._manager.password, firstcmd = True)
		else:
			self._sendCommand("bauth", self._name, firstcmd = True)

		self.lock(True) #lock until inited
		self._pingTask = Task(self._manager, self._pingDelay, True, self.ping)
		self._pingTask.add()
		self._canPing = True
		if not self._reconnecting: self.connected = True

	def _disconnect(self):
		if not self._reconnecting: self.connected = False
		self._pingTask.cancel()
		self.sock.close()

	def disconnect(self):
		self.callEvent("onDisconnect")
		self._disconnect()

	def reconnect(self):
		self._reconnecting = True
		if self.connected:
			self._disconnect()
		self._uid = Generate.uid()
		self._connect()
		self._reconnecting = False

	def _sendCommand(self, *args, firstcmd = False):
		'''Send data to socket'''
		if firstcmd:
			self._write(bytes(':'.join(args)+'\x00', "utf-8"))
		else:
			self._write(bytes(':'.join(args)+"\r\n\x00", "utf-8"))

	def _callEvent(self, event, *args, **kw):
		try:
			getattr(self._manager, event)(self, *args, **kw)
		except AttributeError: pass

	def digest(self, data):
		self._rbuff += data
		commands = data.split(b"\x00")
		for command in commands[:-1]:
			args = command.decode("utf_8").rstrip("\r\n").split(":")
			try:
				if command == b"\r\n":
					getattr(self, "_recv_ping")()
				getattr(self, "_recv_"+args[0])(args[1:])
			except AttributeError: pass
		self._rbuff = commands[-1]
#########################################
#	Commands received from socket
#########################################
	def _recv_ok(self, args):
		if args[2] == "N" and self._manager.password == None and self._manager.username == None: 
			n = args[4].rsplit('.', 1)[0]
			n = n[-4:]
			aid = args[1][4:8]
			self._anon = "!anon" + getAnonId(n, aid)
			self._nColor = n
		elif args[2] == "N" and self._manager.password == None:
			self._sendCommand("blogin", self._manager.username)
		elif args[2] != "M": #unsuccesful login
			self._callEvent("onLoginFail")
			self.disconnect()
		self._owner = args[0]
		self._uid = args[1]	
		self._mods = set(args[6].split(";"))

	def _recv_denied(self, args):
		self._disconnect()
		self._callEvent("onDenied")
	
	def _recv_inited(self, args):
		self._sendCommand("g_participants", "start")
		self._sendCommand("getpremium", "1")
		self._sendCommand("getbannedwords")
		self._sendCommand("getratelimit")
		self._callEvent("onConnect")
		self._callEvent("onHistoryDone", self._history)
		self._history.clear()
		self.lock(False)

	def _recv_premium(self, args):
		if float(args[1]) > time.time():
			self._premium = True
			if self._messageBackground: self.setBgMode(1)
			if self._messageRecord: self.setRecordingMode(1)
		else:
			self._premium = False

	def _recv_g_participants(self, args):
		#g_participants splits people by args
		people = ':'.join(args).split(";")
		for person in people:
			person = person.split(':')
			if person[-2] != "None" and person[-1] == "None":
				self._users.add(person[-2].lower())
				self._userSessions[person[-3]] = person[-2].lower()
		self._callEvent("onParticipants")
	
	def _recv_participant(self, args):
		bit = args[0]
		if bit == '0':	#left
			user = args[3].lower()
			if args[3] != "None" and args[3].lower() in group.users:
				group._users.remove(user)
			self._callEvent("onLeave", user)
		elif bit == '1':	#joined
			user = args[3].lower()
			if args[3] != "None":
				group._users.append(user)
				self._callEvent("onJoin", user)
			else:
				self._callEvent("onJoin", "anon")
		elif bit == '2':	#tempname blogins
			user = args[4].lower()
			group._callEvent("onJoin", user)

	def _recv_bw(self, args):
		self._bannedWords = args[0].split("%2C")

	def _recv_n(self, args):
		self._usercount = int(args[0],16)
		self._callEvent("onUsercount",self._usercount)
		
	def _recv_b(self, args):
		post = _formatMsg(args, 'b')
		if post.time > self._last:
			self._last = post.time
		self._messages[post.pnum] = post

	def _recv_u(self,args):
		post = self._messages.get(args[0])
		if post:
			del self._messages[args[0]]
			post.pid = args[1]
			self._callEvent("onMessage", post)
		else:
			self.call("onDroppedMessage", args)

	def _recv_i(self,args):
		post = _formatMsg(args, 'i')
		self._history.append(post)

	def _recv_gotmore(self, args):
		self._callEvent("onHistoryDone", self._history)
		self._history.clear()
		self._timesGot += 1

	def _recv_show_fw(self, args):
		self._callEvent("onFloodWarning")
	
	def _recv_show_tb(self, args):
		self._callEvent("onFloodBan",int(args[0]))
  
	def _recv_tb(self, args):
		self._callEvent("onFloodBanRepeat",int(args[0]))

	def _recv_blocklist(self, args):
		self._banlist.clear()
		sections = ":".join(args).split(";")
		for section in sections:
			params = section.split(":")
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
		if args[2] == "": return
		target = args[2]
		user = args[3]
		self._banlist.append((args[0], args[1], target, float(args[4]), user))
		self._callEvent("onBan", user, target)
		self.requestBanlist()
  
	def _recv_unblocked(self, args):
		if args[2] == "": return
		target = args[2]
		user = args[3]
		self._callEvent("onUnban", user, target)
		self.requestBanlist()
  
	def _recv_mods(self, args):
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
		msg = self._messages[args[0]]
		if msg:
			self._callEvent("onMessageDelete", msg.user, msg)
  
	def _recv_deleteall(self, args):
		for msgid in args:
			self._recv_delete([msgid])

	def _recv_ping(self, args):
		self._canPing = True

#########################################
#	Frontends to send to socket 
#########################################
	def ping(self):
		if self._canPing:
			self._sendCommand("")
		else:
			self._callEvent("onConnectionLost")
			self._disconnect()

	def sendPost(self, post, channel = 0, html = False):
		'''Send a post to the group'''
		#0 is white, 1 is red, 2 is blue, 3 is both
		#make that into 0 is white, 1 is red, 8 is blue, 9 is both
		#then shift 8 bits and add the channel's default value
		channel = (((channel&2)<<2 | (channel&1))<<8)
		if not html:
			#replace HTML equivalents
			for i,j in reversed(HTML_CODES):
				post = post.replace(j,i)
			post = post.replace("\n","<br/>")
		if len(post) > self._maxLength:
			if self._tooBigMessage == BigMessage_Cut:
				self.message(post[:self._manager._maxLength], html = html)
			elif self._tooBigMessage == BigMessage_Multiple:
				while len(post) > 0:
					sect = post[:self._maxLength]
					post = post[self._maxLength:]
					self.sendPost(sect, html = html)
				return
		self._sendCommand("bm","meme",str(channel),"<n{}/><f x{}{}=\"{}\">{}".format(self.nColor,
			self.fSize, self.fColor, self.fFace, post))

	def addMod(self, user):
		if self.getLevel(self._manager.username) == 2:
			self._sendCommand("addmod", user)

	def removeMod(self, user):
		if self.getLevel(self._manager.username) == 2:
			self._sendCommand("removemod", user)

	def setBgMode(self, mode):
		self._sendCommand("msgbg", str(mode))
  
	def setRecordingMode(self, mode):
		self._sendCommand("msgmedia", str(mode))

	def flag(self, message):
		self._sendCommand("g_flag", message.pnum)

	def delete(self, message):
		if self.getLevel(self.user) > 0:
			self._sendCommand("delmsg", message.pnum)

	def clearUser(self, msg):
		if self.getLevel(self.user) > 0:
			self._sendCommand("delallmsg", msg.unid)

	def clearall(self):
		"""Clear all messages. (Owner only)"""
		if self.getLevel(self.user) == 2:
			self._sendCommand("clearall")
	
	def ban(self, msg):
		"""
		Ban a message's sender. (Moderator only)
		
		@type message: Message
		@param message: message to ban sender of
		"""
		if self.getLevel(self.user) > 0:
			self._sendCommand("block", msg.user, msg.ip, msg.unid)

	def requestBanlist(self):
		"""Request an updated banlist."""
		self._sendCommand("blocklist", "block", "", "next", "500")
  
	def unban(self, user):
		"""
		Unban a user. (Moderator only)
		
		@type user: User
		@param user: user to unban
		
		@rtype: bool
		@return: whether it succeeded
		"""
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

	def getMore(self, amt = 20):
		self._sendCommand("get_more",str(amt),str(self.timesGot))

	def getLevel(self, user):
		if user == self._owner: return 2
		if user in self._mods: return 1
		return 0

class Manager:
	'''THIS WILL CONTAIN ALL (onEvent)S'''
	_socketTimer = .2
	def __init__(self, username, password):
		self.username = username
		self.password = password
		self.running = False
		self.groups = set()
		self.tasks = set()

	def main(self):
		self.onInit()
		self.running = True
		try:
			while self.running:
				socks = [group.sock for group in self.groups]
				read, write, err = select.select(socks,socks,[],self._socketTimer)
				for sock in read:
					group = [i for i in self.groups if i.sock == sock][0]
					try:
						read = sock.recv(1024)
						group.digest(read)
					except socket.error:
						pass
				for sock in write:
#					print("writing socket found")
					group = [i for i in self.groups if i.sock == sock][0]
					try:
						size = sock.send(group.wbuff)
						group.wbuff = group.wbuff[size:]
					except socket.error:
						pass
				self._tick()
		except KeyboardInterrupt: pass

	def _tick(self):
		now = time.time()
		for task in self.tasks:
			if task.target <= now:
				task()

	def joinGroup(self, groupName):
		groupName = groupName.lower()
		if groupName != self.username:
			ret = Group(groupName,self)
			self.groups.add(ret)
			return ret

	def leaveGroup(self, groupName):
		groupName = groupName.lower()
		for group in self.groups:
			if group.name == groupName:
				con.disconnect()
				return

	def getGroup(self, groupName):
		groupName = groupName.lower()
		for group in self.groups:
			if group.name == groupName:
				return group

	def onInit(self):
		pass

def mainThread(username,password):
	instance = Manager(username,password)
	thr = threading.Thread(target=instance.main,daemon=True)
	thr.start()
	return instance
