#!/usr/bin/env python3
'''Client package with customizable display and link opening capabilities.'''

from .base import Box, OverlayBase, Manager, KeyContainer
from .input import ListOverlay, VisualListOverlay \
	, ColorOverlay, ColorSliderOverlay, ConfirmOverlay, DisplayOverlay \
	, TabOverlay, InputOverlay, InputMux
from .chat import CommandOverlay, ChatOverlay, Message, add_message_scroller
from .util import Tokenize, tab_file
from .display import Coloring, colors

on_done = Manager.on_done
start = Manager.start
command = CommandOverlay.command
two56 = colors.two56
raw_num = colors.raw_num
grayscale = colors.grayscale
