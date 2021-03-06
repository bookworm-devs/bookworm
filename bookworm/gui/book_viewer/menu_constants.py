# coding: utf-8

import wx
import enum


class BookRelatedMenuIds(enum.IntEnum):
    """Declares  menu ids for items which are enabled/disabled
    based on whether a book is loaded or not.
    """

    # File
    export = wx.ID_SAVEAS
    pin_document = 205
    closeCurrentFile = 211
    # Tools
    goToPage = 221
    goToPageByLabel = 575
    searchBook = wx.ID_FIND
    findNext = 222
    findPrev = 223
    viewRenderedAsImage = 224
    changeReadingMode = 230


class ViewerMenuIds(enum.IntEnum):
    """Declares menu ids for all other menu items."""

    # Tools menu
    preferences = wx.ID_PREFERENCES
    # Help Menu
    documentation = 801
    website = 802
    license = 803
    contributors = 812
    restart_with_debug = 804
    about = 805


KEYBOARD_SHORTCUTS = {
    wx.ID_OPEN: "Ctrl-O",
    BookRelatedMenuIds.pin_document: "Ctrl-P",
    BookRelatedMenuIds.closeCurrentFile: "Ctrl-W",
    BookRelatedMenuIds.goToPage: "Ctrl-G",
    wx.ID_FIND: "Ctrl-F",
    BookRelatedMenuIds.findNext: "F3",
    BookRelatedMenuIds.findPrev: "Shift-F3",
    BookRelatedMenuIds.viewRenderedAsImage: "Ctrl-R",
    BookRelatedMenuIds.changeReadingMode: "Ctrl-Shift-M",
    wx.ID_PREFERENCES: "Ctrl-Shift-P",
    ViewerMenuIds.documentation: "F1",
}
