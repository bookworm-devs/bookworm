# coding: utf-8

import wx
import wx.lib.sized_controls as sc
from dataclasses import dataclass
from pathlib import Path
from platform_utils.clipboard import copy as copy_to_clipboard, get_text as get_clipboard_text
from slugify import slugify
from bookworm.utils import format_datetime
from bookworm.resources import sounds
from bookworm.logger import logger
from bookworm.gui.components import (
    Dialog,
    SimpleDialog,
    ImmutableObjectListView,
    ColumnDefn,
    make_sized_static_box,
)
from .annotator import (
    Bookmarker,
    NoteTaker,
    Quoter,
    AnnotationFilterCriteria,
    AnnotationSortCriteria,
)
from .exporters import ExportOptions, renderers


log = logger.getChild(__name__)


@dataclass
class FilterAndSortState:
    filter_criteria: AnnotationFilterCriteria
    sort_criteria: AnnotationSortCriteria
    asc: bool

    @classmethod
    def create_default(cls, annotator):
        has_book = annotator.current_book is not None
        book_id = annotator.current_book.id if has_book else None
        return cls(
            filter_criteria=AnnotationFilterCriteria(book_id=book_id),
            sort_criteria=AnnotationSortCriteria.Page
            if has_book
            else AnnotationSortCriteria.Date,
            asc=has_book,
        )


class ViewAndEditAnnotationDialog(SimpleDialog):
    def __init__(self, *args, annotation, editable=False, **kwargs):
        self.annotation = annotation
        self.editable = editable
        self.__saving = False
        super().__init__(*args, **kwargs)

    def addControls(self, parent):
        parent.SetMinSize((500, -1))
        parent.Layout()
        parent.Fit()
        CAN_EDIT = 0 if self.editable else wx.TE_READONLY
        # Translators: label of an edit control in the dialog
        # of viewing or editing a comment/highlight
        wx.StaticText(parent, -1, _("Content"))
        self.contentText = wx.TextCtrl(parent, -1, style=CAN_EDIT | wx.TE_MULTILINE)
        self.contentText.SetSizerProps(expand=True)
        # Translators: header of a group of controls in a dialog to view/edit comments/highlights
        metadataBox = make_sized_static_box(parent, _("Metadata"))
        metadataBox.SetSizerProps(expand=True)
        # Translators: lable of an edit control in a dialog to view/edit comments/highlights
        wx.StaticText(metadataBox, -1, _("Tags"))
        self.tagsText = wx.TextCtrl(metadataBox, -1, style=CAN_EDIT | wx.TE_MULTILINE)
        self.tagsText.SetSizerProps(expand=True)
        if not self.editable:
            # Translators: label of an edit control in a dialog to view/edit comments/highlights
            wx.StaticText(metadataBox, -1, _("Date Created"))
            self.createdText = wx.TextCtrl(
                metadataBox, -1, style=wx.TE_READONLY | wx.TE_MULTILINE
            )
            self.createdText.SetSizerProps(expand=True)
            # Translators: label of an edit control in a dialog to view/edit comments/highlights
            wx.StaticText(metadataBox, -1, _("Last updated"))
            self.updatedText = wx.TextCtrl(
                metadataBox, -1, style=wx.TE_READONLY | wx.TE_MULTILINE
            )
            self.updatedText.SetSizerProps(expand=True)
        if self.editable:
            self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)
        self.set_values()

    def getButtons(self, parent):
        if self.editable:
            return super().getButtons(parent)
        btnsizer = wx.StdDialogButtonSizer()
        # Translators: the label of a button to close a dialog
        btnsizer.AddButton(wx.Button(self, wx.ID_CANCEL, _("&Close")))
        btnsizer.Realize()
        return btnsizer

    def set_values(self):
        self.contentText.Value = self.annotation.content
        self.tagsText.Value = " ".join(self.annotation.tags)
        if not self.editable:
            self.createdText.Value = format_datetime(self.annotation.date_created)
            self.updatedText.Value = format_datetime(self.annotation.date_updated)

    def get_values(self):
        tags = [t.strip() for t in self.tagsText.GetValue().split()]
        return dict(content=self.contentText.GetValue().strip(), tags=tags)

    def onOk(self, event):
        self.__saving = True
        self.Close()

    def ShowModal(self):
        super().ShowModal()
        if self.editable and self.__saving:
            return self.get_values()


class BookmarksViewer(SimpleDialog):
    """A ddialog to view the bookmarks of the current book."""

    def __init__(self, reader, annotator, *args, **kwargs):
        self.view = reader.view
        self.reader = reader
        self.annotator = annotator(self.reader)
        # Translators: label for unnamed bookmarks shown
        # when editing a single bookmark which has no name
        self._unamed_bookmark_title = _("[Unnamed Bookmark]")
        super().__init__(*args, **kwargs)

    def addControls(self, parent):
        # Translators: label of a list control containing bookmarks
        wx.StaticText(parent, -1, _("Saved Bookmarks"))
        self.annotationsListCtrl = ImmutableObjectListView(parent, wx.ID_ANY)
        # Translators: text of a button to remove bookmarks
        wx.Button(parent, wx.ID_DELETE, _("&Remove"))
        self.Bind(
            wx.EVT_LIST_ITEM_ACTIVATED, self.onItemClick, self.annotationsListCtrl
        )
        self.Bind(wx.EVT_LIST_KEY_DOWN, self.onKeyDown, self.annotationsListCtrl)
        self.Bind(
            wx.EVT_LIST_END_LABEL_EDIT, self.onEndLabelEdit, self.annotationsListCtrl
        )
        self.Bind(wx.EVT_BUTTON, self.onDelete, id=wx.ID_DELETE)
        wx.FindWindowById(wx.ID_DELETE).Enable(False)
        self._populate_list()

    def getButtons(self, parent):
        btnsizer = wx.StdDialogButtonSizer()
        # Translators: the label of a button to close a dialog
        btnsizer.AddButton(wx.Button(self, wx.ID_CANCEL, _("&Close")))
        btnsizer.Realize()
        return btnsizer

    def _populate_list(self, focus_target=0):
        annotations = self.annotator.get_for_book()
        column_defn = [
            ColumnDefn(
                # Translators: the title of a column in the bookmarks list
                _("Name"),
                "left",
                250,
                lambda bk: bk.title or self._unamed_bookmark_title,
            ),
            ColumnDefn(
                # Translators: the title of a column in the bookmarks list
                _("Page"),
                "center",
                150,
                lambda bk: bk.page_number + 1,
            ),
        ]
        if self.reader.document.has_toc_tree:
            # Translators: the title of a column in the bookmarks list
            column_defn.append(ColumnDefn(_("Section"), "left", 250, "section_title"))
        self.annotationsListCtrl.set_columns(column_defn)
        self.annotationsListCtrl.set_objects(annotations)
        self.FindWindowById(wx.ID_DELETE).Enable(len(annotations))

    def onItemClick(self, event):
        item = self.annotationsListCtrl.get_selected()
        if item is None:
            return
        self.reader.go_to_page(item.page_number)
        self.Close()
        wx.CallAfter(self.parent.contentTextCtrl.SetFocusFromKbd)
        wx.CallAfter(self.parent.contentTextCtrl.SetInsertionPoint, item.position)

    def onKeyDown(self, event):
        item = self.annotationsListCtrl.get_selected()
        if item is None:
            return
        selected_idx = self.annotationsListCtrl.GetFocusedItem()
        kcode = event.GetKeyCode()
        if kcode == wx.WXK_F2:
            editCtrl = self.annotationsListCtrl.EditLabel(selected_idx)
            if (
                self.annotationsListCtrl.GetItemText(selected_idx)
                == self._unamed_bookmark_title
            ):
                editCtrl.SetValue("")
        elif kcode == wx.WXK_DELETE:
            self.onDelete(event)
        event.Skip()

    def onEndLabelEdit(self, event):
        newTitle = event.GetLabel()
        if newTitle != self._unamed_bookmark_title:
            self.annotator.update(
                item_id=self.annotationsListCtrl.get_selected().id, title=newTitle
            )

    def onDelete(self, event):
        from . import AnnotationService

        item = self.annotationsListCtrl.get_selected()
        if item is None:
            return
        if (
            wx.MessageBox(
                # Translators: content of a message asking the user if they want to delete a bookmark
                _(
                    "This action can not be reverted.\nAre you sure you want to remove this bookmark?"
                ),
                # Translators: title of a message asking the user if they want to delete a bookmark
                _("Remove Bookmark?"),
                parent=self,
                style=wx.YES_NO | wx.ICON_WARNING,
            )
            == wx.YES
        ):
            page_number, pos = item.page_number, item.position
            self.annotator.delete(item.id)
            self._populate_list()
            if page_number == self.reader.current_page:
                AnnotationService.style_bookmark(self.Parent, pos, enable=False)


class AnnotationFilterPanel(sc.SizedPanel):
    """Filter by several criteria."""

    def __init__(
        self, *args, annotator, filter_callback, filter_by_book=False, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.SetSizerProps(expand=True)
        self.SetSizerType("horizontal")
        self.annotator = annotator
        self.filter_callback = filter_callback
        self.filter_by_book = filter_by_book
        if self.filter_by_book:
            # Translators: label of an editable combobox to filter annotations by book
            wx.StaticText(self, -1, _("Book"))
            self.GetSizer().AddSpacer(10)
            self.bookChoice = wx.ComboBox(self, -1)
            self.GetSizer().AddSpacer(20)
        # Translators: label of an editable combobox to filter annotations by tag
        wx.StaticText(self, -1, _("Tag"))
        self.GetSizer().AddSpacer(10)
        self.tagsCombo = wx.ComboBox(self, -1)
        self.GetSizer().AddSpacer(20)
        if not self.filter_by_book:
            # Translators: label of an editable combobox to filter annotations by section
            wx.StaticText(self, -1, _("Section"))
            self.GetSizer().AddSpacer(10)
            self.sectionChoice = wx.ComboBox(self, -1)
            self.GetSizer().AddSpacer(20)
        # Translators: label of an edit control to filter annotations by content
        wx.StaticText(self, -1, _("Content"))
        self.GetSizer().AddSpacer(10)
        self.contentFilterText = wx.TextCtrl(self, -1)
        self.GetSizer().AddSpacer(20)
        # Translators: text of a button to apply chosen filters in a dialog to view user's comments/highlights
        applyButton = wx.Button(self, -1, _("&Apply"))
        self.Bind(wx.EVT_BUTTON, self.onApplyFilter, applyButton)
        self.update_choices()

    def update_choices(self):
        if self.filter_by_book:
            self.bookChoice.Clear()
            for book in self.annotator.get_books_for_model():
                self.bookChoice.Append(book.title, book.id)
        else:
            self.sectionChoice.Clear()
            self.sectionChoice.AppendItems(
                [s[0] for s in self.annotator.get_sections()]
            )
        self.tagsCombo.Clear()
        self.tagsCombo.AppendItems(self.annotator.get_tags())

    def SetFocus(self):
        focusableCtrl = self.bookChoice if self.filter_by_book else self.tagsCombo
        focusableCtrl.SetFocus()

    def onApplyFilter(self, event):
        book_id = None
        if self.filter_by_book:
            book_selection = self.bookChoice.GetSelection()
            if book_selection != wx.NOT_FOUND:
                book_id = self.bookChoice.GetClientData(book_selection)
        self.filter_callback(
            book_id=book_id,
            tag=self.tagsCombo.GetValue().strip(),
            section_title=self.sectionChoice.GetValue().strip()
            if not self.filter_by_book
            else "",
            content=self.contentFilterText.GetValue().strip(),
        )


class AnnotationWithContentDialog(SimpleDialog):
    """View, edit, and manage notes and quotes."""

    @classmethod
    def column_defn(cls):
        return (
            # Translators: the title of a column in the comments/highlights list
            ColumnDefn("Excerpt", "left", 250, lambda a: a.content[:20]),
            # Translators: the title of a column in the comments/highlights list
            ColumnDefn("Section", "left", 200, "section_title"),
            # Translators: the title of a column in the comments/highlights list
            ColumnDefn("Page", "center", 150, lambda anot: anot.page_number + 1),
            # Translators: the title of a column in the comments/highlights list
            ColumnDefn(
                "Added", "right", 200, lambda a: format_datetime(a.date_created)
            ),
        )

    def __init__(self, reader, annotator_cls, *args, can_edit=False, **kwargs):
        self.reader = reader
        self.annotator_cls = annotator_cls
        self.annotator = self.annotator_cls(reader)
        self.can_edit = can_edit
        self.service = wx.GetApp().service_handler.get_service("annotation")
        self._filter_and_sort_state = FilterAndSortState.create_default(self.annotator)
        self._sort_toggles = {}
        super().__init__(*args, **kwargs)

    def addControls(self, parent):
        # Translators: header of a group of controls in a dialog to view user's comments/highlights
        filterBox = make_sized_static_box(parent, _("Filter By"))
        self.filterPanel = AnnotationFilterPanel(
            filterBox,
            -1,
            annotator=self.annotator,
            filter_callback=self.onFilter,
            filter_by_book=not self.reader.ready,
        )
        # Translators: header of a group of controls in a dialog to view user's comments/highlights
        sortBox = make_sized_static_box(parent, _("Sort By"))
        sortPanel = sc.SizedPanel(sortBox, -1)
        sortPanel.SetSizerType("horizontal")
        sortPanel.SetSizerProps(expand=True)
        sort_options = [
            # Translators: text of a toggle button to sort comments/highlights list
            (_("Date"), AnnotationSortCriteria.Date),
            # Translators: text of a toggle button to sort comments/highlights list
            (_("Page"), AnnotationSortCriteria.Page),
        ]
        if not self.reader.ready:
            # Translators: text of a toggle button to sort comments/highlights list
            sort_options.append((_("Book"), AnnotationSortCriteria.Book))
        for bt_label, srt_criteria in sort_options:
            tglButton = wx.ToggleButton(sortPanel, -1, bt_label)
            self._sort_toggles[tglButton] = srt_criteria
            self.Bind(wx.EVT_TOGGLEBUTTON, self.onSortToggle, tglButton)
        # Translators: text of a toggle button to sort comments/highlights list
        self.sortMethodToggle = wx.ToggleButton(sortPanel, -1, _("Ascending"))
        wx.StaticText(parent, -1, self.Title)
        self.itemsView = ImmutableObjectListView(
            parent, id=wx.ID_ANY, style=wx.LC_REPORT | wx.SUNKEN_BORDER
        )
        self.itemsView.SetSizerProps(expand=True)
        self.buttonPanel = sc.SizedPanel(parent, -1)
        self.buttonPanel.SetSizerType("horizontal")
        # Translators: text of a button in a dialog to view comments/highlights
        wx.Button(self.buttonPanel, wx.ID_PREVIEW, _("&View..."))
        if self.can_edit:
            # Translators: text of a button in a dialog to view comments/highlights
            wx.Button(self.buttonPanel, wx.ID_EDIT, _("&Edit..."))
            self.Bind(wx.EVT_BUTTON, self.onEdit, id=wx.ID_EDIT)
        # Translators: text of a button in a dialog to view comments/highlights
        wx.Button(self.buttonPanel, wx.ID_DELETE, _("&Delete..."))
        # Translators: text of a button in a dialog to view comments/highlights
        exportButton = wx.Button(self.buttonPanel, -1, _("E&xport..."))
        self.Bind(wx.EVT_TOGGLEBUTTON, self.onSortMethodToggle, self.sortMethodToggle)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.onItemClick, self.itemsView)
        self.Bind(wx.EVT_LIST_KEY_DOWN, self.onKeyDown, self.itemsView)
        self.Bind(wx.EVT_BUTTON, self.onView, id=wx.ID_PREVIEW)
        self.Bind(wx.EVT_BUTTON, self.onDelete, id=wx.ID_DELETE)
        self.Bind(wx.EVT_BUTTON, self.onExport, exportButton)
        self.on_filter_and_sort_state_changed()
        self.set_items()

    def get_items(self):
        getter_func = (
            self.annotator.get_for_book if self.reader.ready else self.annotator.get_all
        )
        return getter_func(
            self._filter_and_sort_state.filter_criteria,
            self._filter_and_sort_state.sort_criteria,
            self._filter_and_sort_state.asc,
        )

    def set_items(self, items=None):
        items = items or self.get_items()
        self.itemsView.set_columns(self.column_defn())
        self.itemsView.set_objects(items)
        self.itemsView.SetFocusFromKbd()
        if not self.itemsView.ItemCount:
            self.buttonPanel.Disable()

    def on_filter_and_sort_state_changed(self):
        self.set_items(self.get_items())
        self.sortMethodToggle.SetValue(self._filter_and_sort_state.asc)
        for btn, sort_criteria in self._sort_toggles.items():
            if self._filter_and_sort_state.sort_criteria is sort_criteria:
                btn.SetValue(True)
            else:
                btn.SetValue(False)

    def onFilter(self, book_id, tag, section_title, content):
        self._filter_and_sort_state.filter_criteria = AnnotationFilterCriteria(
            book_id=book_id, tag=tag, section_title=section_title, content_snip=content
        )
        self.on_filter_and_sort_state_changed()

    def onSortToggle(self, event):
        if event.IsChecked():
            event.GetEventObject().SetValue(False)
            self._filter_and_sort_state.sort_criteria = self._sort_toggles[
                event.GetEventObject()
            ]
        self.on_filter_and_sort_state_changed()

    def onSortMethodToggle(self, event):
        self._filter_and_sort_state.asc = event.IsChecked()
        self.on_filter_and_sort_state_changed()

    def go_to_item(self, item):
        self.reader.go_to_page(item.page_number)

    def onItemClick(self, event):
        item = self.itemsView.get_selected()
        if item is not None:
            self.Close()
            self.go_to_item(item)

    def view_or_edit(self, is_viewing=True):
        item = self.itemsView.get_selected()
        if item is None:
            return wx.Bell()
        editable = self.can_edit and not is_viewing
        dlg = ViewAndEditAnnotationDialog(
            self,
            # Translators: title of a dialog to view or edit a single comment/highlight
            title=_("Editing") if editable else _("View"),
            annotation=item,
            editable=editable,
        )
        with dlg:
            return dlg.ShowModal()

    def onView(self, event):
        self.view_or_edit(is_viewing=True)

    def onDelete(self, event):
        item = self.itemsView.get_selected()
        if item is None:
            return
        if (
            wx.MessageBox(
                # Translators: content of a message asking the user if they want to delete a comment/highlight
                _(
                    "This action can not be reverted.\nAre you sure you want to remove this item?"
                ),
                # Translators: title of a message asking the user if they want to delete a bookmark
                _("Delete Annotation?"),
                parent=self,
                style=wx.YES_NO | wx.ICON_WARNING,
            )
            == wx.YES
        ):
            self.annotator.delete(item.id)
            self.filterPanel.update_choices()
            self.set_items(self.get_items())

    def onEdit(self, event):
        if not self.can_edit:
            return
        updates = self.view_or_edit(is_viewing=False)
        if updates:
            item = self.itemsView.get_selected()
            self.annotator.update(item.id, **updates)
            self.filterPanel.update_choices()
            self.set_items()

    def onKeyDown(self, event):
        item = self.itemsView.get_selected()
        if item is None:
            return
        kcode = event.GetKeyCode()
        if kcode == wx.WXK_DELETE:
            self.onDelete(event)
        elif kcode == wx.WXK_F6:
            self.filterPanel.SetFocus()
        elif kcode == wx.WXK_F2:
            self.edit_tags(item)
        elif wx.GetKeyState(wx.WXK_CONTROL) and (kcode == 67):
            try:
                if get_clipboard_text() != item.content:
                    copy_to_clipboard(item.content)
                    sounds.clipboard.play()
            except:
                log.exception("Failed to copy annotation text to the clipbard", evc_info=True)
        event.Skip()

    def edit_tags(self, item):
        new_tags = self.service.view.get_text_from_user(
            # Translators: title of a dialog that allows the user to edit the tag set of a comment/highlight
            title=_("Edit Tags"),
            # Translators: label of an edit control that allows the user to edit the tag set of a comment/highlight
            label=_("Tags"),
            value=" ".join(item.tags),
        )
        if new_tags is not None:
            self.annotator.update(item.id, tags=[t.strip() for t in new_tags.split()])
            self.filterPanel.update_choices()

    def onExport(self, event):
        items = tuple(self.get_items())
        # Translators: title of a dialog that allows the user to customize
        # how comments/highlights are exported
        with ExportNotesDialog(parent=self, title=_("Export Options")) as dlg:
            retval = dlg.ShowModal()
            if retval is None:
                return wx.Bell()
            renderer_cls, open_after_export, export_options = retval
            self.export_items(renderer_cls, items, export_options, open_after_export)

    def export_items(self, renderer_cls, items, export_options, open_after_export):
        renderer = renderer_cls(
            items, export_options, self._filter_and_sort_state.filter_criteria
        )
        resulting_file = renderer.render_to_file()
        if open_after_export:
            wx.LaunchDefaultApplication(resulting_file)


class GenericAnnotationWithContentDialog(AnnotationWithContentDialog):
    @classmethod
    def column_defn(cls):
        column_defn = list(super().column_defn())
        # Translators: the title of a column in the comments/highlights list
        column_defn.insert(
            1, ColumnDefn(_("Book"), "left", 300, lambda a: a.book.title)
        )
        return column_defn

    def set_default_state(self):
        self._filter_and_sort_state.sort_criteria = AnnotationSortCriteria.Date
        self._filter_and_sort_state.asc = False

    def go_to_item(self, item):
        def book_load_callback():
            super(GenericAnnotationWithContentDialog, self).go_to_item(item)
            if isinstance(self.annotator, NoteTaker):
                self.service.view.set_insertion_point(item.position)
            else:
                self.service.view.select_text(item.start_pos, item.end_pos)

        self.service.view.open_file(item.book.file_path, callback=book_load_callback)


class CommentsDialog(AnnotationWithContentDialog):
    def go_to_item(self, item):
        super().go_to_item(item)
        self.service.view.set_insertion_point(item.position)


class QuotesDialog(AnnotationWithContentDialog):
    def go_to_item(self, item):
        super().go_to_item(item)
        self.service.view.select_text(item.start_pos, item.end_pos)


class ExportNotesDialog(SimpleDialog):
    """Customization for note exporting."""

    def addControls(self, parent):
        self._save = False
        # Translators: label of a checkbox in a dialog to set export options for comments/highlights
        self.includeBookTitleCheckbox = wx.CheckBox(parent, -1, _("Include book title"))
        self.includeSectionTitleCheckbox = wx.CheckBox(
            # Translators: label of a checkbox in a dialog to set export options for comments/highlights
            parent,
            -1,
            _("Include section title"),
        )
        self.includePageNumberCheckbox = wx.CheckBox(
            # Translators: label of a checkbox in a dialog to set export options for comments/highlights
            parent,
            -1,
            _("Include page number"),
        )
        # Translators: label of a checkbox in a dialog to set export options for comments/highlights
        self.includeTagsCheckbox = wx.CheckBox(parent, -1, _("Include tags"))
        # Translators: label of a choice control in a dialog to set export options for comments/highlights
        wx.StaticText(parent, -1, _("Output format:"))
        self.formatChoice = wx.Choice(
            parent, -1, choices=[r.display_name for r in renderers]
        )
        # Translators: label of an edit control in a dialog to set export options for comments/highlights
        wx.StaticText(parent, -1, _("Output File"))
        self.outputFileTextCtrl = wx.TextCtrl(
            parent, -1, style=wx.TE_READONLY | wx.TE_MULTILINE
        )
        # Translators: text of a button in a dialog to set export options for comments/highlights
        browseButton = wx.Button(parent, -1, _("&Browse..."))
        self.openAfterExportCheckBox = wx.CheckBox(
            parent,
            -1,
            # Translators: label of a checkbox in a dialog to set export options for comments/highlights
            _("Open file after exporting"),
        )
        self.Bind(wx.EVT_BUTTON, self.onBrowse, browseButton)
        self.Bind(wx.EVT_BUTTON, self.onSubmit, id=wx.ID_OK)
        self.formatChoice.SetSelection(0)
        checkboxs = (
            self.includeBookTitleCheckbox,
            self.includeSectionTitleCheckbox,
            self.includePageNumberCheckbox,
            self.includeTagsCheckbox,
            self.openAfterExportCheckBox,
        )
        for cb in checkboxs:
            cb.SetValue(True)

    @property
    def selected_renderer(self):
        return [
            rend
            for rend in renderers
            if rend.display_name == self.formatChoice.GetStringSelection()
        ][0]

    def onBrowse(self, event):
        saveExportedFD = wx.FileDialog(
            self,
            # Translators: the title of a save file dialog asking the user for a filename to export annotations to
            _("Save As"),
            defaultDir=wx.GetUserHome(),
            defaultFile="",
            wildcard=(
                f"{_(self.selected_renderer.display_name)} (*{self.selected_renderer.output_ext})"
                f"|{self.selected_renderer.output_ext}"
            ),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if saveExportedFD.ShowModal() == wx.ID_OK:
            self.outputFileTextCtrl.SetValue(saveExportedFD.GetPath().strip())
        saveExportedFD.Destroy()

    def onSubmit(self, event):
        if not self.outputFileTextCtrl.GetValue().strip():
            self.outputFileTextCtrl.SetFocus()
            return wx.Bell()
        self._save = True
        self.Close()

    def ShowModal(self):
        super().ShowModal()
        if self._save:
            return (
                self.selected_renderer,
                self.openAfterExportCheckBox.IsChecked(),
                ExportOptions(
                    output_file=self.outputFileTextCtrl.GetValue().strip(),
                    include_book_title=self.includeBookTitleCheckbox.IsChecked(),
                    include_section_title=self.includeSectionTitleCheckbox.IsChecked(),
                    include_page_number=self.includePageNumberCheckbox.IsChecked(),
                    include_tags=self.includeTagsCheckbox.IsChecked(),
                ),
            )
