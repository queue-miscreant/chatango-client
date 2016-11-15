#uid  :: user id
#unid :: unique user id, in base 64
#pid :: post id, after display
#pnum :: post number, before display
#
#major TODO: implement threaded stuff and ping
'''
b
:1479201115.43		#0
:c0debreak			#1	user
:					#2	tempname
:45951550			#3:	user id
:					#4	(something mod related), user id in b64
:ChMM1YStrsrDXiAjGtuduA==	#5
:					#6	(ip)
:0					#7	channel
:					#8	######################################################## :<n3c0/><f x120cc=""><b>@cubebert: `Flagged that message` Grill&#39;s been reported to chatango&#39;s secret police<br/></b>


i
:1479200010.45		#0: time
:cubebert			#1: user
:					#2	tempname
:61230343			#3:	user id
:					#4	(something mod related), user id in b64
:2Z2wwF23NwI0oVg=	#5	message id assigned after display
:					#6	(ip)
:0					#7	channel
:					#8	########################################################
:<n3355ff/><f x120ecd64="8">But there appears to be a command for it



Message before refresh:

from u:
	2Z2wwF23NQM0p10=

i:1479201666.65:cubebert::82894187:1yNRtZGRN5ekjk7Bu1uBbw==:2Z2wwF23NQM0p10=:64.189.165.191:256::<n000/><f x12f96="1">and if i switch channels?
	2Z2wwF23NQM0p10=

'''



import socket
import time
import threading
import re
import select

AUTH_RE = re.compile("auth\.chatango\.com ?= ?(.*?);")
POST_TAG_RE = re.compile("(<n([a-fA-F0-9]{1}|[a-fA-F0-9]{3}|[a-fA-F0-9]{4}|[a-fA-F0-9]{6})\/>)?(<f x([\d]{0}|[\d]{2})([0-9a-fA-F]{1}|[0-9a-fA-F]{3}|[0-9a-fA-F]{6})=\"([0-9a-zA-Z]*)\">)?")
XML_TAG_RE = re.compile("(<.*?>)")
THUMBNAIL_FIX_RE = re.compile(r"(https?://ust.chatango.com/.+?/)t(_\d+.\w+)")

HTML_CODES = [
	["&#39;","'"],
	["&gt;",">"],
	["&lt;","<"],
	["&quot;",'"'],
	["&apos;","'"],
	["&amp;",'&'],
]
def _formatRaw(raw):
	if len(raw) == 0: return raw
	#replace <br>s with actual line breaks
	#otherwise, remove html
	for i in XML_TAG_RE.findall(raw):
		raw = raw.replace(i,i == "<br/>" and "\n" or "")
	raw.replace("&nbsp;",' ')
	for i in HTML_CODES:
		raw = raw.replace(i[0],i[1])
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
		,"post": formatRaw(":".join(raw[9:]))
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
	

class Generate:
	def uid():
		'''Generate unique ID'''
		str(int(random.randrange(10 ** 15, (10 ** 16) - 1)))

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

class Manager:
	'''THIS WILL CONTAIN ALL (onEvent)S'''
	def __init__(self, username, password, pm):
		self.username = username
		self.password = password
		self.pm = pm
		self.running = False
		self.groups = []

	def manage(self, data):
		socks = [group.sock for group in self.groups]
		read, write, err = select.select(socks,socks,[])
		for i,sock in enumerate(read):
			group = self.groups[i]
			rbuff = b""					#reading buffer
			lenread = -1
			try:
				while lenread and rbuff[-1] != b'\x00':
					read = self.chSocket.recv(1024)
					lenread = len(read)
					rubff += read
				if lenread: #!=0
					group.digest(rbuff)
			except socket.error:
				pass
		for i,sock in enumerate(write):
			group = self.groups[i]
			try:
				size = sock.send(group.wbuff)
				group.wbuff = group.wbuff[size:]
			except socket.error:
				pass
			
class Group:
	def __init__(self, room, manager = None):
		self._server = server or getServer(room)
		self._port = port or 443
		self.sock = None
		self.wbuff = b""
		self._wbufflock = b""
		self._wlock = False

		self.manager = manager

		self._name = room
		self._owner = None
		self._uid = Generate.uid()
		self._aid = None
		self._aname  = None
		#chatango needs nameColor here, so the rest are here too
		self._nColor = None	
		self._fSize  = None
		self._fColor = None
		self._fFace  = None
		self._mods = []

		self._connected = False
		self._reconnecting = False
		if manager: self._connect()

	def lock(self,lock):
		'''Lock/unlock writing buffer'''
		self._wlock = lock
		if not lock:
			self.wbuff += self._wbufflock
			self._wbufflock = b""

	def _write(self,data):
		'''Write to writing buffer'''
		if self._wlock:
			self.wbuff += data
		else:
			self._wbufflock += data
	
	def _connect(self):
		'''Connect to the server.'''
		self.sock = socket.socket()
		self.sock.connect((self._server, self._port))
		self.sock.setblocking(False)
		self.wbuff = b""
		#authenticate
		if self.manager.name and self.manager.password:
			self._sendCommand("bauth", self.name, self._uid, self.manager.name, self.manager.password)
		else:
			self._sendCommand("bauth", self.name)

		self._setWriteLock(True) #lock until inited
#		self._pingTask = self.mgr.setInterval(self.mgr._pingDelay, self.ping)
		if not self._reconnecting: self.connected = True

	def _disconnect(self):
		if not self._reconnecting: self.connected = False
		self.users = {}
		self.userlist = []
#		self._pingTask.cancel()
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
			getattr(self.manager, event)(self, *args, **kw)
		except AttributeError: pass

	def _digest(self, data):
		for cmd in data.split(b"\x00"):
			args = data.decode("utf_8").rstrip("\r\n").split(":")
			try:
				if len(args) == 1:
					getattr(self, "_recv_ping")()
				getattr(self, "_recv_"+args[0])(args[1:])
			except AttributeError: pass
#########################################
#	Commands received from socket
#########################################
	def _recv_ok(self, args):
		if args[2] == "N" and self.manager.password == None and self.manager.name == None: 
			n = args[4].rsplit('.', 1)[0]
			n = n[-4:]
			aid = args[1][4:8]
			self._aname = "!anon" + getAnonId(n, aid)									#bound name _aname to anon name
			self._nColor = n															#bound name _nColor to name color
		elif args[2] == "N" and self.manager.password == None:
			self._sendCommand("blogin", self.manager.name)
		elif args[2] != "M": #unsuccesful login
			self._callEvent("onLoginFail")
			self.disconnect()
		self._owner = args[0]															#bound name _owner to room owner
		self._uid = args[1]																#bound name _uid to unique id
		self._aid = args[1][4:8]														#bound name _aid to anon id
		self._mods = set(args[6].split(";"))											#bound name _mods to moderators

	def _recv_denied(self, args):
		self._disconnect()
		self._callEvent("onDenied")
	
	def _recv_inited(self, args):
		self.sendCommand("g_participants", "start")
		self.sendCommand("getpremium", "1")
		self.sendCommand("getbannedwords")
		self.sendCommand("getratelimit")
		self._callEvent("onConnect")
		self.lock(False)

	def _recv_premium(self, args):
		if float(args[1]) > time.time():
			self._premium = True														#bound name _premium to whether account is premium
			#TODO make this code work
#			if self.user._mbg: self.setBgMode(1)
#			if self.user._mrec: self.setRecordingMode(1)
		else:
			self._premium = False

	def _recv_g_participants(self, args):
		#g_participants splits people by args
		people = ':'.join(args).split(";")
		for person in people:
			person = person.split(':')
			if person[-2] != "None" and person[-1] == "None":
				self._users.append(person[-2].lower())									#bound name _users to list of registered chatango users
				self._userSessions[person[-3]] = person[-2].lower()						#bound name _userSessions to list of user sessions (uids)
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
		group._bannedWords = args[0].split("%2C")										#bound name _bannedWords to banned words list

	def _recv_n(self, args):
		self._usercount = int(args[0],16)												#bound name _usercount to user count
		self._callEvent("onUsercount",self._usercount)
		
	def _recv_b(self, args):
		#TODO function that extrapolates i and b
		post = _formatMsg(args, 'b')
		if post.time > self._last:
			self._last = post.time														#bound name _last to last most recent message time
		self._messages[post.pnum] = type("Post", (object,),								#bound name _messages to message array
			{"time": time
			,"user": user
			,"pid":	None
			,"uid": args[3]
			,"unid": args[4]
			,"pnum": args[5]
			,"ip": args[6]
			,"channel":(chval&1|(chval&8)>>2)
			,"post": formatRaw(":".join(args[9:]))
			,"nColor": nColor
			,"fSize": fSize
			,"fFace": fFace
			,"fColor": fColor})

	def _recv_u(self,args):
		post = group._messages.get(args[0])
		if post:
			post.pid = args[1]
			self._callEvent("onMessage", post)
		else:
			self.call("onDroppedMessage", args)

	def _recv_i(self,args):
		post = _formatMsg(args, 'i')
		self._history.append(post)														#bound name _history to historical messages

	def _recv_gotmore(self, args):
		self._callEvent("onHistoryDone", self._history)
		self._history.clear()
		self._timesGot += 1																#bound name _timesGot to times gotmore has been fired

	def _recv_show_fw(self, args):
		self._callEvent("onFloodWarning")
	
	def _recv_show_tb(self, args):
		self._callEvent("onFloodBan",int(args[0]))
  
	def _recv_tb(self, args):
		self._callEvent("onFloodBanRepeat",int(args[0]))

	def rcmd_blocklist(self, args):
		self._banlist = list()															#bound name _banlist to ban list
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
#		self.requestBanlist()															TODO code for requestbanlist
  
	def _recv_unblocked(self, args):
		if args[2] == "": return
		target = args[2]
		user = args[3]
		self._callEvent("onUnban", user, target)
#		self.requestBanlist()
  
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
			if msg in self._history:
				self._history.remove(msg)
				self._callEvent("onMessageDelete", msg.user, msg)
				msg.detach()
  
	def _recv_deleteall(self, args):
		for msgid in args:
			self._recv_delete([msgid])

	def _recv_ping(self, args):
		self._canPing = True													#bound name _canPing to ability to ping without disconnecting

#########################################
#	Frontends to send to socket XXX
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
		channel = self.channel+(((channel&2)<<2 | (channel&1))<<8)
		if not html:
			#replace HTML equivalents
			for i,j in reversed(HTML_CODES):
				post = post.replace(j,i)
			post = post.replace("\n","<br/>")
		if len(post) > self.maxLength:
			if self.manager._tooBigMessage == BigMessage_Cut:
				self.message(post[:self.manager._maxLength], html = html)
			elif self.manager._tooBigMessage == BigMessage_Multiple:
				while len(post) > 0:
					sect = post[:self._maxLength]
					post = post[self._maxLength:]
					self.sendPost(sect, html = html)
				return
		self._sendCommand("bm","meme",str(channel),"<n{}/><f x{}{}=\"{}\">{}".format(self.nColor,
			self.fSize, self.fColor, self.fFace, post))
	
		
	def addMod(self, user):
		if self.getLevel(self.user) == 2:											#bound name user to username
			self._sendCommand("addmod", user)

	def removeMod(self, user):
		if self.getLevel(self.user) == 2:											#bound name user to username
			self._sendCommand("removemod", user)

