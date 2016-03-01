from os import environ
import curses
import time
import re

environ.setdefault('ESCDELAY', '25')

_COLOR_NAMES = [" Red","Green"," Blue"]

#debug stuff
def dbmsg(*args):
	with open("debug","a+") as a:
		for i in args:
			a.write(str(i)+"\t")
		a.write("\n")
		a.close()

#list of curses keys
#used internally to redirect curses keys
_CURSES_KEYS = {
	9:  'tab',	#htab
	10: 'enter',	#line feed
	13: 'enter',	#carriage return
	27: 'escape',	#escape
	127:'backspace',#delete character
}
for i in dir(curses):
	if "KEY" in i:
		_CURSES_KEYS[getattr(curses,i)] = i
_CURSES_KEYS[curses.KEY_ENTER] = 'enter'
_CURSES_KEYS[curses.KEY_BACKSPACE] = 'backspace'

indent = 4
cursorchar = "_"

colorers = []
commands = {}
filters = []

class link_opener:
#	__init__ is like a static __call__
	def __init__(self,client,link):
		#extension
		ext = link[link.rfind(".")+1:].lower()
		try:
			if len(ext) <= 4 and hasattr(self,ext):
				getattr(self, ext)(client,link,ext)
			else:
				getattr(self, 'htmllink')(client,link)
		except AttributeError as exc:
			pass
class schedule:
	def __init__(self):
		self.scheduler = []
		self.taskno = 0
		self.debounce = False
	
	def __call__(self,func,*args):
		if self.debounce:
			self.scheduler.append((func,args))
			return True
		func(*args)
		self.taskno+=1
	
	def bounce(self,newbounce):
		prev = self.debounce
		self.debounce = newbounce
		if not newbounce:
			while self.taskno < len(self.scheduler):
				task = self.scheduler[self.taskno]
				task[0](*task[1])
				self.taskno+=1
			self.scheduler = []
			self.taskno = 0
		return prev

scheduler = schedule()

#conversions to and from hex strings ([255,255,255] <-> FFFFFF)
def toHexColor(rgb):
	return ''.join([hex(i)[2:].rjust(2,'0') for i in rgb])
def fromHexColor(hexStr):
	return [int(hexStr[2*i:2*i+2],16) for i in range(3)]

def colorPairs():
	#control colors
	curses.init_pair(1,curses.COLOR_RED,    curses.COLOR_WHITE)     # red on white for system
	curses.init_pair(2,curses.COLOR_RED,    curses.COLOR_RED)       #drawing red boxes
	curses.init_pair(3,curses.COLOR_GREEN,  curses.COLOR_GREEN)     #drawing green boxes
	curses.init_pair(4,curses.COLOR_BLUE,   curses.COLOR_BLUE)      #drawing blue boxes

#add take out links, add them to a list
def parseLinks(raw,lastlinks):
	#in case the raw message ends wzith a link
	newLinks = []
	#look for whole word links starting with http:// or https://
	newLinks = [i for i in re.findall("(https?://.+?\\.[^ \n]+)[\n ]",raw+" ")]
	#don't add the same link twice
	for i in newLinks:
		while newLinks.count(i) > 1:
			newLinks.remove(i)
	#lists are passed by reference
	lastlinks += newLinks
	return raw

#new wrapping; better time efficiency
def unicodeWrap(fullString,byteString,width):
	try:
		byted = len(byteString[:width].decode())
		return fullString[:byted], fullString[byted:]
	except:
		return unicodeWrap(fullString,byteString,width-1)

#split message into lines to add into the curses display
def splitMessage(baseMessage, width):
	#parts of the message
	parts = []
	w = width

	for split in baseMessage.split('\n'):
		#add an indent for messages after the first newline
		#keep splitting up the words
		wide = bytes(split,'utf-8')
		while len(wide) >= w:
			#look for a space in the later half of the string; if none, do a hard split
			lastSpace = wide.rfind(b' ',w//2,w+1)
			if lastSpace + 1:
				sub,split = unicodeWrap(split,wide,lastSpace)
				split = split[1:]
			else: #otherwise split at the last character in the row
				sub, split = unicodeWrap(split,wide,w)

			parts.append(sub)
			wide = bytes(split,'utf-8')
			w = width-indent

		if split.count(' ') != len(split):
			parts.append(split)
		w = width-indent

	return parts
#get the last "width" unicode bytes of fullString
def easyWrap(fullString,width):
	fullString = fullString[::-1]
	ret,_ = unicodeWrap(fullString,bytes(fullString,'utf-8'),width)
	#unicode wrapping
	return ret[::-1]

class cursesInput:
	def __init__(self,screen):
		self.screen = screen
		self._debounce = False
	#usually for loop control
	def onescape(self):
		return -1

	def input(self):
		chars = [self.screen.getch()]
		#get as many chars as possible
		prev = scheduler.bounce(True)
		self.screen.nodelay(1)
		next = 0
		while next+1:
			next = self.screen.getch()
			chars.append(next)
		self.screen.nodelay(0)
		scheduler.bounce(prev)
		#control sequences

		curseAction = _CURSES_KEYS.get(chars[0])
		try:
			if curseAction and len(chars) == 2:
				return getattr(self,"on"+curseAction)()
			elif chars[0] in range(32,255):
				getattr(self,"oninput")(chars[:-1])
		except AttributeError:
			pass

	def addKeys(self,newFunctions = {}):
		for i,j in newFunctions.items():
			if type(i) == str:
				setattr(self,"on"+i,j)
			else:
				setattr(self,"on"+_CURSES_KEYS[i],j)

	def bounce(self,newbounce):
		self._debounce = newbounce

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

	def makeWindows(self, height, width):
		#drawing calls are expensive, especially when drawing the chat
		#which means that you have to live with fullscreen lists
		#height,width,y,x = (int(i) for i in [height*.5, width*.8, height*.2, width*.1])
		if width < 7 or height < 3 : raise SizeException()
		self.display = curses.newwin(height-3,width,0,0)

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
			getattr(self,'drawOther')(self,maxy,maxx)

		display.refresh()
	
	#predefined list iteration methods
	def onKEY_UP(self):
		self.it -= 1
		self.it %= len(self.outList)
	def onKEY_DOWN(self):
		self.it += 1
		self.it %= len(self.outList)

	#loop until escape
	def loop(self):
		self.draw()
		while self.input() != -1:
			self.draw()

class colorInput(listInput):
	def __init__(self, screen,initcolor = [127,127,127]):
		listInput.__init__(self,screen,[])
		self.color = initcolor

	def draw(self):
		display = self.display

		display.clear()
		display.border()
		maxy,maxx = display.getmaxyx()
		part = maxx//3-1

		third = lambda x: x*(part)+x+1
		centered = lambda x: x.rjust((part+len(x))//2).ljust(part)
		try:
			self.display.addstr(maxy-2,third(1),centered(toHexColor(self.color)))

			for i in range(3):
				#gibberish for "draw a pretty rectange of the color it represents"
				for j in range(1+int((maxy-6)*(1 - self.color[i]/255)),maxy-6):
					display.addstr(j,third(i)," "*part,curses.color_pair(i+2))

				display.addstr(maxy - 5, third(i), centered(COLOR_NAMES[i]),
					self.mode == i and curses.A_REVERSE)
				display.addstr(maxy - 4, third(i), centered(" %d"%self.color[i]),
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

		self.lines = lines
		self.numlines = 0
		self.redraw()
	
	def subWindow(self,subwin):
		scheduler.bounce(True)
		subwin.loop()
		scheduler(self.win.redrawwin)
		scheduler(self.win.refresh)
		scheduler.bounce(False)

	def _redraw(self):
		#clear the window
		self.win.clear()
		self.numlines = 0
		#draw all chat windows
		for data in self.lines:
			self._drawline(data) 
		#refresh
		self.win.hline(self.height, 0, curses.ACS_HLINE, self.width)
		self.win.refresh()
	
	#format expected: (string, coldic)
	def _push(self, newmsg):
		self.lines.append(newmsg)
		
		self._drawline(newmsg)
		self.win.hline(self.height, 0, curses.ACS_HLINE, self.width)
		self.win.refresh()
	
	def push(self,newmsg):
		scheduler(self._push,newmsg)
	
	def redraw(self):
		scheduler(self._redraw)

	def _drawline(self, newmsg):
		#don't draw if filtered
		try:
			if not all(i(*newmsg[2]) for i in filters): return
		except: pass
		
		newlines = splitMessage(newmsg[0],self.width)[-self.height:]
		lenlines = len(newlines)
		colors = newmsg[1]
		
		calc = min(self.numlines,self.height-lenlines)
		#scroll some lines if needed
		if self.numlines == self.height: self.win.scroll(lenlines)
		wholetr = 0
		for i,line in enumerate(newlines):
			linetr = 0
			unitr = 0
			for j in sorted(colors.keys()):
				if wholetr+linetr < j:
					#error found
					part = line[linetr:min(j,len(line))]
					try:
						self.win.addstr(calc+i, unitr+((i!=0) and indent), part, colors[j])
					except:
						raise SizeException()
					linetr = min(j,len(line))
					unitr += len(bytes(part,'utf-8'))
					if j > len(line): break
			wholetr += len(line)
		
		self.numlines = min(self.height,self.numlines+lenlines)

class chatinput:
	def __init__(self, height, width):
		self.width = width
		#create chat window, input window...
		win = lambda x: curses.newwin(1, width, height + x, 0)
		
		self.inputWin = win(0)			#two after chat
		self.debugWin = win(1)			#three after chat
		self.statWin = win(2)			#last line for status
		
		self.debugWin.leaveok(1)
		self.statWin.leaveok(1)
		self.args = ("","")
	
		self.statWin.attron(curses.A_STANDOUT)
	
	def _inrefresh(self, input):
		if input is not None:
			self.inputWin.clear()
			self.inputWin.addstr(0,0,input)
		self.inputWin.refresh()
		
	def _statrefresh(self,*args):
		if len(args) == 2: 
			args = [i for i in map(str,args)]
			self.args = args
		elif len(args) == 0: args = self.args
		else: return

		try:
			self.statWin.hline(' ',self.width-1)
			self.statWin.addstr(0,0,args[0])
			self.statWin.addstr(0,self.width-len(args[1])-1,args[1])
		except:
			raise SizeException()
		self.statWin.refresh()
	
	def _blurbrefresh(self,message):
		self.debugWin.clear()
		self.debugWin.addnstr(0,0,message,self.width)
		self.debugWin.refresh()
	
	def inrefresh(self, input = None):
		scheduler(self._inrefresh,input)
	
	def statrefresh(self,*args):
		scheduler(self._statrefresh,*args)
	
	def blurbrefresh(self,message = ""):
		scheduler(self._blurbrefresh,message)

class scrollable:
	_text = ""
	pos = 0
	disp = 0
	history = []
	selhis = 0
	
	def __init__(self,width):
		self.width = width
	
	def __call__(self):
		return self._text

	def append(self,new):
		self._text = self._text[:self.pos] + new + self._text[self.pos:]
		self.movepos(len(new))
	
	def backspace(self):
		if not self.pos: return #don't backspace at the beginning of the line
		self._text = self._text[:self.pos-1] + self._text[self.pos:]
		self.movepos(-1)

	def clear(self):
		self._text = ""
		self.pos = 0
		self.disp = 0

	def movepos(self,dist):
		self.pos = max(0,min(len(self._text),self.pos+dist))
		if (self.pos == self.disp and self.pos != 0) or self.pos - self.disp >= self.width:
			self.disp += dist
	
	def display(self):
		text = self._text[:self.pos] + cursorchar + self._text[self.pos:]
		text = text.replace("\n",r"\n").replace("\t",r"\t").replace("\r",r"\r")
		text = text[self.disp:self.disp+self.width]
		return easyWrap(text,self.width)

	def nexthist(self):
		if len(self.history) > 0:
			self.selhis += (self.selhis < (len(self.history)))
			self._text = self.history[-self.selhis]
			self.pos = len(self._text)
		
	def prevhist(self):
		if len(self.history) > 0:
			self.selhis -= (self.selhis > 0)
			#the next element or an empty string
			self._text = self.selhis and self.history[-self.selhis] or ""
			self.pos = len(self._text)
	
	def appendhist(self,new):
		self.history.append(new)
		self.history = self.history[-50:]
		self.selhis = 0
	
class client(cursesInput):
	lastlinks = []
	last = 0

	def __init__(self,screen):
		cursesInput.__init__(self,screen)
		self.active = True
		y,x = self.screen.getmaxyx()
		self.text = scrollable(x-1)
		self.chat = chat(y-3,x)
		self.inputwin = chatinput(y-3,x)
		curses.curs_set(0)

	#simple method to output to the chat window
	def msgSystem(self, base):
		self.chat.push((base,{len(base): curses.color_pair(1)}))
	
	def msgPost(self, post, *args):
		post = parseLinks(post,self.lastlinks)
		
		coldic = {}
		for i in colorers:
			i(post,coldic,*args)
		if coldic.get('default'):
			coldic.pop('default')
		coldic = {i:j for i,j in coldic.items() if j is not None}
		
		self.chat.push((post,coldic,list(args)))
	
	def msgTime(self, numtime, predicate=""):
		dtime = time.strftime("%H:%M:%S",time.localtime(numtime))
		self.msgSystem(predicate+dtime)
	
	def newBlurb(self,message = ""):
		self.last = time.time()
		self.inputwin.blurbrefresh(message)
				
	def onbackspace(self):
		self.text.backspace()
	
	def onenter(self):
		#if it's not just spaces
		text = self.text()
		if text.count(" ") != len(text):
			#good thing strings are scalars
			self.text.clear()
			#if it's a command
			if text[0] == '/' and ' ' in text:
				try:
					command = getattr(commands,text[1:text.find(' ')])
					command(text[text.find(' ')+1:].split(' '))
				finally:
					return
			self.text.appendhist(text)
			self.chatBot.tryPost(text)
	
	def oninput(self,chars):
		#allow unicode input
		self.text.append(bytes(chars).decode())

	def onKEY_SHOME(self):
		self.text.clear()
		self.shistory = 0

	def onKEY_LEFT(self):
		self.text.movepos(-1)
	
	def onKEY_RIGHT(self):
		self.text.movepos(1)

	def onKEY_UP(self):
		self.text.nexthist()
		
	def onKEY_DOWN(self):
		self.text.prevhist()
		
	def onKEY_F2(self):
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
		self.chat.subWindow(box)
		
	#threaded function that prints the current time every 10 minutes
	#also handles erasing blurbs
	def timeloop(self):
		i = 0
		while self.active:
			time.sleep(2)
			i+=1
			if time.time() - self.last > 4:
				self.newBlurb()
			#every 600 seconds
			if not i % 300:
				self.msgTime(time.time())
				i=0

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
			setattr(client,"on"+_CURSES_KEYS[keyname],func)
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

#exceptions
class DisconnectException(Exception):
	pass

class SizeException(Exception):
	pass
