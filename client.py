#!/usr/bin/env python3
#
#client.py:
#	Curses-based tentatively "general purpose" client
#
#Uses curses to display chat, with individual names being summed into colors
#Replies and system messages are special colors
#Historical messages are underlined
#

from os import environ
import curses
import time
import re
#curses likes to wait a second on escape by default. Turn that off
environ.setdefault('ESCDELAY', '25')

COLOR_NAMES = [" Red","Green"," Blue"]

#debug stuff
def dbmsg(*args):
	with open("debug","a+") as a:
		for i in args:
			a.write(str(i)+"\t")
		a.write("\n")
		a.close()

#predefined keys
#if you want to define more key events, you'll want to use
#a method titled onKEY_(key)
#check the curses module for the key names
CURSES_KEYS = {	
	9:  'tab',
	10: 'enter',
	13: 'enter',
	27: 'escape',
	127:'backspace',
}
for i in dir(curses):
	if "KEY" in i:
		CURSES_KEYS[getattr(curses,i)] = i
CURSES_KEYS[curses.KEY_ENTER] = 'enter'
CURSES_KEYS[curses.KEY_BACKSPACE] = 'backspace'

colorers = []
commands = {}
filters = []

class link_opener:
#	__init__ is like a static __call__
	def __init__(self,client,link):
		#extension
		ext = link[link.rfind(".")+1:]
		try:
			if len(ext) <= 4 and hasattr(self,ext):
				getattr(self, ext)(client,link,ext)
			else:
				getattr(self, 'htmllink')(client,link)
		except AttributeError as exc:
			pass

def colorPairs():
	#control colors
	curses.init_pair(1,curses.COLOR_RED,	curses.COLOR_WHITE)	# red on white for system
	curses.init_pair(2,curses.COLOR_RED,	curses.COLOR_RED)	#drawing red boxes
	curses.init_pair(3,curses.COLOR_GREEN,	curses.COLOR_GREEN)	#drawing green boxes
	curses.init_pair(4,curses.COLOR_BLUE,	curses.COLOR_BLUE)	#drawing blue boxes

#add take out links, add them to a list
def parseLinks(raw,lastlinks):
	#in case the raw message ends wzith a link
	raw += " "
	newLinks = []
	#look for whole word links starting with http:// or https://
	newLinks = [i for i in re.findall("(https?://.+?\\.[^ \n]+)[\n ]",raw)]
	#don't add the same link twice
	for i in newLinks:
		while newLinks.count(i) > 1:
			newLinks.remove(i)
	
	for i,link in enumerate(newLinks):
		raw = raw.replace(link,"<LINK %d>" % (len(lastlinks)+i+1))
	#lists are passed by reference
	lastlinks += newLinks
	#remove trailing space
	return raw[:-1]

#split message into lines to add into the curses display
def splitMessage(baseMessage, width, indent = 4):
	#parts of the message
	parts = []
	w = width
	
	for split in baseMessage.split("\n"):
		#add an indent for messages after the first newlineB
		#keep splitting up the words
		wide = bytes(split,'utf-8')
		while len(wide) >= w:
			sub, split = wordWrap(split,w,wide)
			parts.append(sub)
			wide = bytes(split,'utf-8')
			w = width-indent
			
		if split.count(" ") != len(split):
			parts.append(split)
		w = width-indent
		
	return parts
#split string into parts if in the middle of a word at the width, with unicode support
#it just works, trust me
#bytestring passed so that bytes doesn't need to be calculated many times
def wordWrap(fullString, width, byteString):
	#width+1 in case the next character is a space
	#if it's the middle of the word, split it at the last space
	if b' ' in byteString[:width+1]:
		lastSpace = byteString.rfind(b" ",width//2,width+1)
		if lastSpace + 1:
			a,b = unicodeWrap(fullString,lastSpace)
			return a,b[1:]
	#otherwise split at the last character in the row
	return unicodeWrap(fullString,width)
#wrap function based on byte length of characters
def unicodeWrap(fullString,width):
	i,j = 0,0
	while j < width and i < len(fullString):
		j += len(bytes(fullString[i],'utf-8'))
		i += 1
	return fullString[:i], fullString[i:]

def easyWrap(fullString,width):
	ret,_ = unicodeWrap(fullString[::-1],width-1)
	#unicode wrapping
	return ret[::-1]
#conversions to and from hex strings ([255,255,255] <-> FFFFFF)
def toHexColor(rgb):
	return ''.join([hex(i)[2:].rjust(2,'0') for i in rgb])
def fromHexColor(hexStr):
	return [int(hexStr[2*i:2*i+2],16) for i in range(3)]

class cursesInput:
	def __init__(self,screen):
		self.screen = screen
		self.debounce = False
	#usually for loop control
	def onescape(self):
		return -1
		
	def input(self):
		screen = self.screen
		chars = [screen.getch()]
		#get as many chars as possible
		self.bounce(True)
		screen.nodelay(1)
		next = 0
		while next+1:
			next = screen.getch()
			chars.append(next)
		screen.nodelay(0)
		self.bounce(False)
		#control sequences
		
		curseAction = CURSES_KEYS.get(chars[0])
		try:
			if curseAction and len(chars) == 2:
				return getattr(self,"on"+curseAction)()
			elif chars[0] in range(32,255):
				getattr(self,"oninput")(chars[:-1])
		except AttributeError:
			pass
	
	def bounce(self,newbounce):
		self.debounce = newbounce

class listInput(cursesInput):
	it = 0
	mode = 0
	
	def __init__(self, screen, outList, drawOther = None):
		cursesInput.__init__(self, screen)	
		self.outList = outList
		height, width = screen.getmaxyx()
		self.makeWindows(height, width)
		#turn the cursor off
		curses.curs_set(0)
		if drawOther:
			setattr(self,'drawOther',drawOther)
			
	def addKeys(self,newFunctions = {}):
		for i,j in newFunctions.items():
			if type(i) == str:
				setattr(self,"on"+i,j)
			else:
				setattr(self,"on"+CURSES_KEYS[i],j)
		
	def makeWindows(self, height, width):
		#drawing calls are expensive, especially when drawing the chat
		#which means that you have to live with fullscreen lists
		#height,width,y,x = (int(i) for i in [height*.5, width*.8, height*.2, width*.1])
		height,width = height-3,width
		if width < 7 or height < 3 : raise SizeException()
		self.display = curses.newwin(height,width,0,0)
	
	#draw method for previous method's window
	def draw(self):
		display = self.display
		#make sure the display is legitimate
		maxy,maxx = display.getmaxyx()
		maxy-=2
		maxx-=2
		#clear, make a border
		display.erase()
		display.border()
		#which portion of the list is currently displaced
		listNum = self.it//maxy
		subList = self.outList[maxy*listNum:min(maxy*(listNum+1),len(self.outList))]
		#display
		for i,value in enumerate(subList):
			#add an elipsis in the middle of the string if it can't be displayed
			if len(value) > maxx:
				half = maxx//2
				value = value[:half - 3] + "..." + value[-half:]
			display.addstr(i+1,1,value,(i+maxy*listNum == self.it) and curses.A_STANDOUT)
		if hasattr(self,'drawOther'):
			getattr(self,'drawOther')(self)
			
		display.refresh()
	
	#predefined list iteration methods
	def onKEY_UP(self):
		self.it -= 1
		if self.it == -1:
			self.it = len(self.outList)-1
	def onKEY_DOWN(self):
		self.it += 1
		if self.it == len(self.outList):
			self.it = 0
	
	#loop until escape
	def loop(self):
		ret = None
		while True:
			self.draw()
			ret = self.input()
			if ret is not None: break
			
		return ret

class colorInput(listInput):
	def __init__(self, screen,initcolor = [127,127,127]):
		listInput.__init__(self,screen,[])
		self.color = initcolor
		
	def draw(self):
		display = self.display
		
		display.clear()
		display.border()
		h, w = display.getmaxyx()
		part = w//3-1
		
		third = lambda x: x*(part)+x+1
		centered = lambda x: x.rjust((part+len(x))//2).ljust(part)
		starty = lambda x:1+int((h-6)*(1 - self.color[x]/255))
		try:
			self.display.addstr(h-2,third(1),centered(toHexColor(self.color)))
						
			for i in range(3):
				#gibberish for "draw a pretty rectange of the color it represents"
				for j in range(starty(i),h-6):
					display.addstr(j,third(i)," "*part,curses.color_pair(i+2))
				
				display.addstr(h - 5, third(i), centered(COLOR_NAMES[i]),
					self.mode == i and curses.A_REVERSE)
				display.addstr(h - 4, third(i), centered(" %d"%self.color[i]),
					self.mode == i and curses.A_REVERSE)
		except:
			raise SizeException()
		
		display.refresh()
	#color manipulation: mode represents color selected
	#up/down: increment/decrement color
	#left/right: select color
	#pgup/pgdn: increment/decrement color by 10
	#home/end: set color to 255/0
	def onKEY_UP(self):
		self.color[self.mode] += 1
		if self.color[self.mode] > 255:
			self.color[self.mode] = 255
		
	def onKEY_DOWN(self):
		self.color[self.mode] -= 1
		if self.color[self.mode] < 0:
			self.color[self.mode] = 0
		
	def onKEY_PPAGE(self):
		self.color[self.mode] += 10	
		if self.color[self.mode] > 255:
			self.color[self.mode] = 255
		
	def onKEY_NPAGE(self):
		self.color[self.mode] -= 10
		if self.color[self.mode] < 0:
			self.color[self.mode] = 0
		
	def onKEY_HOME(self):
		self.color[self.mode] = 255
		
	def onKEY_END(self):
		self.color[self.mode] = 0
		
	def onKEY_RIGHT(self):
		self.mode = (self.mode + 1) % 3
		
	def onKEY_LEFT(self):
		self.mode = (self.mode - 1) % 3

class chat:
	def __init__(self, maxy, maxx, lines = []):
		self.height = maxy-1
		self.width = maxx
		self.win = curses.newwin(maxy,maxx)
		self.win.scrollok(1)
		self.win.setscrreg(0,maxy-2)
		self.win.leaveok(1)
		self.nums = 0
		self.lineno = 0
		self.lines = lines
		self._debounce = False
		self.redraw()
		
	def redraw(self):
		if self._debounce: return
		#clear the window
		self.win.clear()
		#draw all chat windows
		self.nums = 0
		for data in self.lines:
			self.drawline(data) 
		#refresh
		self.win.refresh()
	
	#format expected: (string, coldic)
	def push(self, newmsg, append = True):
		self.lines.append(newmsg)
		if self._debounce: return
		self.lineno+=1
		try:
			if not all(i(*newmsg[2]) for i in filters): return
		except: pass
		self.drawline(newmsg)
		self.win.refresh()
		
	def drawline(self, newmsg):
		newlines = splitMessage(newmsg[0],self.width)[-self.height:]
		colors = newmsg[1]
		
		calc = min(self.nums,self.height-len(newlines))
		#scroll some lines if needed
		if self.height-self.nums <= 0:
			self.win.scroll(len(newlines))
		wholetr = 0
		for i,line in enumerate(newlines):
			linetr = 0
			linecol = {}
			for j in sorted(colors.keys()):
				if wholetr+linetr < j:
					#error found
					try:
						self.win.addstr(calc+i, linetr+((i!=0) and 4), line[linetr:min(j,len(line))], colors[j])
					except:
						raise SizeException()
					linetr = min(j,len(line))
					if j > len(line): break
			wholetr += len(line)
			#self.win.addnstr(calc+i, 0, line[0], self.width, line[1])
		self.win.hline(self.height, 0, curses.ACS_HLINE, self.width)
		
		self.nums = min(self.height,self.nums+len(newlines))
	
	def bounce(self, newbounce):
		self._debounce = newbounce;
		if not newbounce:
			while (self.lineno < len(self.lines)):
				self.drawline(self.lines[self.lineno])
				self.lineno+=1
			self.lines = self.lines[-100:]
			self.lineno = len(self.lines)
			#scroll garbage from superwindows off the screen
			self.win.touchwin()	
			self.win.refresh()
			
class chatinput:
	def __init__(self, height, width, count = 0):
		self.width = width
		self.count = count
		#create chat window, input window...
		win = lambda x: curses.newwin(1, width, height + x, 0)
		
		self.inputWin = win(0)			#two after chat
		self.debugWin = win(1)			#three after chat
		self.statWin = win(2)			#last line for status
		
		self.debugWin.leaveok(1)
		self.statWin.leaveok(1)
		
		self.statWin.attron(curses.A_STANDOUT)
	
	def inrefresh(self, input = None):
		if input is not None:
			self.inputWin.clear()
			split = easyWrap(input.replace("\n",r"\n").replace("\t",r"\t").replace("\r",r"\r"),self.width-1)
			self.inputWin.addnstr(0,0,split,self.width-1)
		self.inputWin.refresh()
		
	def statrefresh(self, name, count = None):		
		if count is None: count = self.count
		else: self.count = count
		
		repeat = self.width - len(name) - len(str(count)) - 1
		if repeat <= 0: raise SizeException()
		self.statWin.addstr(0,0,"{}{}{}".format(name," "*repeat,str(count)))
		self.statWin.refresh()
		self.inputWin.refresh()
	
	def blurbrefresh(self,message = ""):
		self.debugWin.clear()
		self.debugWin.addnstr(0,0,message,self.width)
		self.debugWin.refresh()
		self.inputWin.refresh()
		
class client(cursesInput):
	lastlinks = []
	history = []
	selectHistory = 0
	text = ""
	lastBlurb = 0
	
	def __init__(self,screen):
		cursesInput.__init__(self,screen)
		self.active = True
		y,x = screen.getmaxyx()
		self.chat = chat(y-3,x)
		self.inputwin = chatinput(y-3,x)
		self.chat.redraw()
	
	#simple method to output to the chat window
	def newMessage(self, base):
		self.chat.push((base,{len(base): curses.color_pair(1)}))
		self.inputwin.inrefresh()
	
	def newPost(self, post, *args):
		post = parseLinks(post,self.lastlinks)
		
		coldic = {}
		for i in colorers:
			i(post,coldic,*args)
		if coldic.get('default'):
			coldic.pop('default')
		coldic = {i:j for i,j in coldic.items() if j is not None}
		
		self.chat.push((post,coldic,list(args)))
		self.inputwin.inrefresh()
	
	def printTime(self, predicate="", numtime=None):
		if numtime is None: numtime = time.time()
		dtime = time.strftime("%H:%M:%S",time.localtime(numtime))
		self.newMessage(predicate+dtime)
	
	def printBlurb(self,message = ""):
		self.lastBlurb = time.time()
		self.inputwin.blurbrefresh(message)
				
	def onbackspace(self):
		self.text = self.text[:-1]
		self.inputwin.inrefresh(self.text)
	
	def onenter(self):
		#if it's not just spaces
		text = self.text
		if text.count(" ") != len(text):
			#good thing strings are scalars
			self.text = ""
			self.inputwin.inrefresh(self.text)
			#if it's a command
			if text[0] == '/' and ' ' in text:
				try:
					command = getattr(commands,text[1:text.find(' ')])
					command(text[text.find(' ')+1:].split(' '))
				finally:
					return
			
			self.history.append(text)
			if len(self.history) > 50:
				self.history.pop(0)
			self.chatBot.tryPost(text)
	
	def oninput(self,chars):
		#allow unicode input
		new = bytes(chars).decode()
		self.text += new
		self.inputwin.inrefresh(self.text)

	def onKEY_SHOME(self):
		self.text = ""
		self.inputwin.inrefresh(self.text)
	
	def onKEY_UP(self):
		if len(self.history) > 0:
			self.selectHistory -= (self.selectHistory > 0)
			self.text = self.history[self.selectHistory]
			self.inputwin.inrefresh(self.text)
		
	def onKEY_DOWN(self):
		if len(self.history) > 0:
			self.selectHistory += (self.selectHistory < len(self.history))
			#the next element or an empty string
			self.text = self.selectHistory != len(self.history) and self.history[self.selectHistory] or ""
			self.inputwin.inrefresh(self.text)
		
	def onKEY_F2(self):
		self.chat.bounce(True)
		#special wrapper to inject functionality for newlines in the list
		def select(me):
			def ret():
				if not len(self.lastlinks): return
				current = self.lastlinks[len(self.lastlinks) - 1 - me.it]
				if not me.mode:
					link_opener(self,current)
				else:
					paste(current)
				#exit
				return -1
			return ret
		
		#take out the protocol
		dispList = [i.replace("http://","").replace("https://","") for i in reversed(self.lastlinks)]
		#link number: link, but in reverse
		dispList = ["{}: {}".format(len(self.lastlinks)-i,j) for i,j in enumerate(dispList)] 
	
		box = listInput(self.screen, dispList)
		box.addKeys({
			'enter':select(box),
			curses.KEY_RESIZE:resize(box,self)
		})
		#direct input away from normal input
		box.loop()
	
		curses.curs_set(1)
		self.chat.bounce(False)
		
	#threaded function that prints the current time every 10 minutes
	#also handles erasing blurbs
	def timeloop(self):
		i = 0
		while self.active:
			time.sleep(2)
			i+=1
			if time.time() - self.lastBlurb > 4:
				self.printBlurb()
			#every 600 seconds
			if not i % 300:
				self.printTime()
				i=0
	
	def bounce(self,newbounce):
		self.debounce = newbounce
		self.chat.bounce(newbounce)

#generic wrapper for redrawing listinputs
def resize(self,replace):
	def ret():
		y, x = self.screen.getmaxyx()
		replace.onKEY_RESIZE()
		self.makeWindows(y,x)
	return ret

#DID SOMEONE SAY DECORATORS?
def onkey(keyname):
	def wrapper(func):
		if type(keyname) == str:
			setattr(client,"on"+keyname,func)
		else:
			setattr(client,"on"+CURSES_KEYS[keyname],func)
	return wrapper

def command(commandname):
	def wrapper(func):
		commands[commandname] = func
	return wrapper
	
def colorer(func):
	colorers.append(func)

def chatfilter(func):
	filters.append(func)

def opener(extension):
	def wrap(func):
		setattr(link_opener,extension,staticmethod(func))
		#allow stacking wrappers
		return func
	return wrap

class DisconnectException(Exception):
	pass

class SizeException(Exception):
	pass
