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
def formatRaw(raw):
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

class Generate:
	def uid():
		'''Generate unique ID'''
		str(int(random.randrange(10 ** 15, (10 ** 16) - 1)))

	def aid(n, aid):
		'''Generate anon ID'''
		if n == None: n = "3452"
		try:
			return "".join(map(lambda i,v: str(int(i) + int(v))[-1],
						   str(n), aid[4:]))
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
		self.digest = Digest(self)

		self.name = room
		self.uid = Generate.uid()
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
		self._users = {}
		self._userlist = []
#		self._pingTask.cancel()
		self._sock.close()

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

	def callEvent(self, event, *args, **kw):
		try:
			getattr(self.manager, event)(self, *args, **kw)
		except AttributeError: pass

	def sendCommand(self, *args, firstcmd = False):
		'''Send data to socket'''
		if firstcmd:
			self._write(bytes(':'.join(args)+"\x00", "utf-8"))
		else:
			self._write(bytes(':'.join(args)+"\r\n\x00", "utf-8"))

	def getUsers(self):
		return self._userlist

class Digest:
	def __init__(self,group):
		self.group = group

	def __call__(self,data):
		for cmd in data.split(b"\x00"):
			args = raw.decode("utf_8").rstrip("\r\n").split(":")
			try:
				getattr(self, args[0])(self.group, args)
			except AttributeError: pass

	def _callback(self,event,*args,**kwargs):
		self.group.callEvent(event,*args,**kwargs)

	def b(self, args):
		'''message...'''
		pass

	def ok(self, args):
		if args[2] == "N" and self.group.manager.password == None and self.group.manager.name == None: 
			n = args[4].rsplit('.', 1)[0]
			n = n[-4:]
			aid = args[1][0:8]
			pid = "!anon" + getAnonId(n, aid)
			#TODO move these to the actual group
			self.group.aname = pid
			self.group.nameColor = n
		elif args[2] == "N" and self.mgr.password == None:
		  self._sendCommand("blogin", self.mgr.name)
		elif args[2] != "M": #unsuccesful login
		  self._callback("onLoginFail")
		  self.disconnect()
		self.owner = args[0]
		self.group.uid = args[1]
		self.group.aid = args[1][4:8]
		self.group.mods = set(map(args[6].split(";")))
	
	def inited(self, args):
		self.group.sendCommand("g_participants", "start")
		self.group.sendCommand("getpremium", "1")
		self.group.requestBanlist()
		group.sendCmd("getbannedwords")
		group.sendCmd("getratelimit")
		self._callback("onConnect")
		self.group.lock(False)






























class Group:
	def __init__(self, manager, group, user, password, uid, pm):
		self._name = room
		self._server = server or getServer(room)
		self._port = port or 443
		self._manager = manager

		self._uid = str(int(random.randrange(10 ** 15, (10 ** 16) - 1)))	#unique id

		self._wbuff = b""
		self._rbuff = b""
		self._wlockbuff = b""
		self._wlock = False;
		
		self.socket = None

		if self.name != self.user: #group variables
		else: #PM variables
			self.nColor = "000"
			self.pmAuth = None
			self.ip = None
			self.fl = list()
			self.bl = list()
			self.prefix = None
		self.connect()
	
	def _lock(self, lock):
		self._wlock = lock
		if not lock:
			self._write(self._wlockbuff)
			self._wlockbuff = b""

	def _write(self,data):
		if self._wlock:
			self._wlockbuff += data
		else:
			self._manager.write(data)

	def _connect(self):
		'''connect to socket'''
		self.socket = socket.socket()
		self._sock.connect((self._server, self._port))
		self.socket.setblocking(False)
		self._wbuf = b""
		self._auth()
#		self._pingTask = self.mgr.setInterval(self.mgr._pingDelay, self.ping)
		if not self._reconnecting: self.connected = True
	
	def _auth(self):
		self.sendCmd("bauth", self.name, self._uid, self._manager.name, self._manager.password, firstcmd=True)

	def reconnect(self)
		self._reconnecting = True
		if self.connected:
		  self._disconnect()
		self._uid = genUid()
		self._connect()
		self._reconnecting = False

'''
		try:
			if self.name != self.user:
				self.chSocket.connect(("s{}.chatango.com".format(self.snum), 443))
				self.sendCmd("bauth", self.name, self.uid, self.user, self.password, firstcmd=True)
			else:
				self.chSocket.connect(("c1.chatango.com", 5222))
				self.pmAuth = Generate.auth(self)
				self.sendCmd("tlogin", self.pmAuth, "2", self.uid, firstcmd=True)
			self.connected = True
			self.manager.connected = True
'''

	def manage(self):
		rbuf = b""
		wbuf = b""
		try:
			rSock, wSock, eSock = select.select([self.chSocket], [self.chSocket], [self.chSocket])
		except:
			self.manager.removeGroup(self)
		if wSock:
			try:
				wbuf = self.wqueue.get_nowait()
				self.chSocket.send(wbuf)
			except queue.Empty:
				pass
			except socket.error:
				self.manager.removeGroup(self)
			except:
				self.manager.removeGroup(self)
		if rSock:
			while not rbuf.endswith(b'\x00'):
				try:
					rbuf += self.chSocket.recv(1024) #need the WHOLE buffer ;D
				except:
					self.manager.removeGroup(self.name)
			if len(rbuf) > 0:
				self.manager.manage(self, rbuf)

	def ping(self):
		'''Ping? Pong!'''
		self.sendCmd("\r\n\x00")

	def cleanPM(self, pm):
		'''Clean's all PM XML'''
		return XML_TAG_RE.sub("", pm)

	def sendPost(self, post, channel = 0, html = False):
		'''Send a post to the group'''
		#0 is white, 1 is red, 2 is blue, 3 is both
		#make that into 0 is white, 1 is red, 8 is blue, 9 is both
		#then shift 8 bits and add the channel's default value
		channel = self.channel+(((channel&2)<<2 | (channel&1))<<8)
		if not html:
			#replace HTML equivalents
			for i in reversed(HTML_CODES):
				post = post.replace(i[1],i[0])
			post = post.replace("\n","<br/>")
		if len(bytes(post,'utf-8')) < 2700 and self.limited == 0:
			self.sendCmd("bm","meme",str(channel),"<n{}/><f x{}{}=\"{}\">{}".format(self.nColor,
				self.fSize, self.fColor, self.fFace, post))

	def sendCmd(self, *args, firstcmd = False):
		'''Send data to socket'''
		if firstcmd:
			self.wqueue.put_nowait(bytes(':'.join(args)+"\x00", "utf-8"))
		else:
			self.wqueue.put_nowait(bytes(':'.join(args)+"\r\n\x00", "utf-8"))

	def getMore(self, amt = 20):
		self.sendCmd("get_more",str(amt),str(self.timesGot))

	def getBanList(self):
		'''Retreive ban list'''
		self.blist = list()
		self.sendCmd("blocklist", "block", "", "next", "500")

	def getLastPost(self, match, data = "user"):
		'''Retreive last post object from user'''
		try:
			post = sorted([x for x in list(self.pArray.values()) if getattr(x, data) == match], key=lambda x: x.time, reverse=True)[0]
		except:
			post = None
		return post

	def login(self, user, password = None):
		'''Login to an account or as a temporary user or anon'''
		if user and password:
			self.user = user
			self.sendCmd("blogin", user, password) #user
		elif user:
			self.user = "#" + user
			self.sendCmd("blogin", user) #temporary user
		else:
			self.user = "!anon" + Generate.aid(self.nColor, self.uid)

	def logout(self):
		'''Logs out of an account'''
		self.sendCmd("blogout")

	def enableBg(self):
		'''Enables background'''
		self.sendCmd("getpremium", "1")

	def disableBg(self):
		'''Disables background'''
		self.sendCmd("msgbg", "0")

	def enableVr(self):
		'''Enable group's VR on each post'''
		self.sendCmd("msgmedia", "1")

	def disableVr(self):
		'''Disable group's VR on each post'''
		self.sendCmd("msgmedia", "0")

	def setNameColor(self, nColor):
		'''Set's a user's name color'''
		#anons can't do this because of chatango
		if self.user[0] == '!': return
		self.nColor = nColor

	def setFontColor(self, fColor):
		'''Set's a user's font color'''
		self.fColor = fColor

	def setFontSize(self, fSize):
		'''Set's a user's font size'''
		fSize = str(fSize)
		if 9 <= int(fSize) <= 22:
			if len(fSize) == 1:
				fSize = "0"+fSize
			self.fSize = fSize

	def setFontFace(self, fFace):
		'''Set's a user's font face'''
		self.fFace = fFace

	def getAuth(self, user):
		'''return the users group level 2 = owner 1 = mod 0 = user'''
		if user == self.owner:
			return 2
		if user in self.mods:
			return 1
		else:
			return 0

	def getBan(self, user):
		'''Get banned object for a user'''
		banned = [x for x in self.blist if x.user == user]
		if banned:
			return banned[0]
		else:
			return None

	def dlPost(self, post):
		'''delete a user's post'''
		self.sendCmd("delmsg", post.pid)

	def dlUser(self, user):
		'''Delete all of a user's posts'''
		post = self.getLastPost(user)
		unid = None
		if post:
			unid = post.unid
		if unid:
			if post.user[0] in ["!","#"]:
				self.sendCmd("delallmsg", unid, post.ip, "")
			else:
				self.sendCmd("delallmsg", unid, post.ip, post.user)

	def ban(self, user):
		'''Ban a user'''
		unid = None
		ip = None
		try:
			unid = self.getLastPost(user).unid
			ip = self.getLastPost(user).ip
		except:
			pass
		if unid and ip:
			if user[0] in ['#', '!']:
				self.sendCmd("block", unid, ip, "")
			else:
				self.sendCmd("block", unid, ip, user)
		self.getBanList()

	def flag(self, user):
		'''Flag a user'''
		pid = self.getLastPost(user).pid
		self.sendCmd("g_flag", pid)

	def unban(self, user):
		'''Unban a user'''
		banned = [x for x in self.blist if x.user == user]
		if banned:
			self.sendCmd("removeblock", banned[0].unid, banned[0].ip, banned[0].user)
			self.getBanList()

	def setMod(self, mod):
		'''Add's a group moderator'''
		self.sendCmd("addmod", mod)

	def eraseMod(self, mod):
		'''Removes a group moderator'''
		self.sendCmd("removemod", mod)

	def clearGroup(self):
		'''Deletes all messages'''
		if self.user == self.owner:
			self.sendCmd("clearall")
		else: #;D
			pArray = self.pArray.values()
			for user in list(set([x.user for x in pArray])):
				post = self.getLastPost(user)
				if post and hasattr(post, "unid"):
					self.dlUser(user)

################################
#Connections Manager
#Handles: New Connections and Connection data
################################

class Manager(object):
	def __init__(self, name = None, password = None, pm = True):
		self._name = name
		self._password = password
		self._running = False
		self._tasks = set()		#
		self._rooms = dict()	#list of rooms with the groups the represent
		'''
		if pm:
			self._pm = self._PM(mgr = self) 
		else:
			self._pm = None
		'''
	'''
	def __init__(self, user, password, pm):
		self.user = user.lower()
		self.name = self.user
		self.password = password
		if self.password and not self.user: #password supplied but not username
			self.password = None
		self.pm = pm
		self.cArray = list()
		self.eArray = dict()
		self.eArray[self.name] = list()
		self.groups = list()
		self.wbuf = b""
		self.uid = str(int(random.randrange(10 ** 15, (10 ** 16) - 1)))
		self.prefix = None
		self.acid = Digest(self)
		self.connected = any([x.connected for x in self.cArray])
	'''

	def stop(self):
		'''disconnect from all groups'''
		g = list(self.cArray)
		for group in g:
			self.removeGroup(group.name)

	def addGroup(self, group):
		'''Join a group'''
		if not self.getGroup(group) in self.cArray:
			group = Group(self, group, self.user, self.password, self.uid, self.pm)
			self.cArray.append(group)
			if group.name != self.user:
				self.groups.append(group.name)

	def removeGroup(self, group):
		'''Leave a group'''
		group = self.getGroup(group)
		if group in self.cArray:
			group.connected = False
			self.cArray.remove(group)
			if group.name != self.user:
				self.groups.remove(group.name)
			for event in self.eArray[group.name]:
				event.cancel()
			group.chSocket.close()
			self.recvRemove(group)
		if not self.cArray:
			self.connected = False

	def getEvent(self, group, name):
		event = [x for x in self.eArray[group.name] if x.name == name]
		return event[0] if event else None

	def getGroup(self, group):
		'''Get a group object'''
		group = [g for g in self.cArray if g.name == group]
		if group:
			return group[0]

	def getUser(self, user):
		'''Get all groups a user is in'''
		groups = list()
		for group in self.cArray:
			if hasattr(group, "users"):
				if user.lower() in group.users:
					groups.append(group.name)
		if groups:
			return groups
		else:
			return None

	def sendPM(self, user, pm):
		'''Send's a PM'''
		group = self.getGroup(self.user)
		self.sendCmd("msg", user, "<n{}""/><m v=\"1\"><g xs0=\"0\"><g x{}s{}=\"{}\">{}</g></g></m>".format(group.nColor
			,group.fSize
			,group.fColor
			,group.fFace
			,pm))

	def sendCmd(self, *args):
		'''Send data to socket'''
		self.getGroup(self.user).wqueue.put_nowait(bytes(':'.join(args)+"\r\n\x00", "utf-8"))

	def manage(self, group, data):
		buffer = data.split(b"\x00")
		for raw in buffer:
			if raw:
				self.acid.digest(group, raw)

	def main(self):
		if self.pm:
			self.addGroup(self.user)
		while self.connected:
			try:
				time.sleep(1)
			except KeyboardInterrupt:
				self.stop()
				exit(0)
