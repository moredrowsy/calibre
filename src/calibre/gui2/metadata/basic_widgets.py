#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2011, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import textwrap, re, os

from PyQt4.Qt import (Qt, QDateEdit, QDate, pyqtSignal,
    QIcon, QToolButton, QWidget, QLabel, QGridLayout,
    QDoubleSpinBox, QListWidgetItem, QSize, QPixmap,
    QPushButton, QSpinBox, QLineEdit, QSizePolicy)

from calibre.gui2.widgets import EnLineEdit, FormatList, ImageView
from calibre.gui2.complete import MultiCompleteLineEdit, MultiCompleteComboBox
from calibre.utils.icu import sort_key
from calibre.utils.config import tweaks, prefs
from calibre.ebooks.metadata import title_sort, authors_to_string, \
        string_to_authors, check_isbn
from calibre.ebooks.metadata.meta import get_metadata
from calibre.gui2 import file_icon_provider, UNDEFINED_QDATE, UNDEFINED_DATE, \
        choose_files, error_dialog, choose_images, question_dialog
from calibre.utils.date import local_tz, qt_to_dt
from calibre import strftime, fit_image
from calibre.ebooks import BOOK_EXTENSIONS
from calibre.customize.ui import run_plugins_on_import
from calibre.utils.date import utcfromtimestamp
from calibre.gui2.comments_editor import Editor
from calibre.library.comments import comments_to_html
from calibre.gui2.dialogs.tag_editor import TagEditor

'''
The interface common to all widgets used to set basic metadata
class BasicMetadataWidget(object):

    LABEL = "label text"

    def initialize(self, db, id_):
        pass

    def commit(self, db, id_):
        return True

    @dynamic_property
    def current_val(self):
        # Present in most but not all basic metadata widgets
        def fget(self):
            return None
        def fset(self, val):
            pass
        return property(fget=fget, fset=fset)
'''

# Title {{{
class TitleEdit(EnLineEdit):

    TITLE_ATTR = 'title'
    COMMIT = True
    TOOLTIP = _('Change the title of this book')
    LABEL = _('&Title:')

    def __init__(self, parent):
        self.dialog = parent
        EnLineEdit.__init__(self, parent)
        self.setToolTip(self.TOOLTIP)
        self.setWhatsThis(self.TOOLTIP)

    def get_default(self):
        return _('Unknown')

    def initialize(self, db, id_):
        title = getattr(db, self.TITLE_ATTR)(id_, index_is_id=True)
        self.current_val = title
        self.original_val = self.current_val

    def commit(self, db, id_):
        title = self.current_val
        if self.COMMIT:
            getattr(db, 'set_'+ self.TITLE_ATTR)(id_, title, notify=False)
        else:
            getattr(db, 'set_'+ self.TITLE_ATTR)(id_, title, notify=False,
                    commit=False)
        return True

    @dynamic_property
    def current_val(self):

        def fget(self):
            title = unicode(self.text()).strip()
            if not title:
                title = self.get_default()
            return title

        def fset(self, val):
            if hasattr(val, 'strip'):
                val = val.strip()
            if not val:
                val = self.get_default()
            self.setText(val)
            self.setCursorPosition(0)

        return property(fget=fget, fset=fset)

class TitleSortEdit(TitleEdit):

    TITLE_ATTR = 'title_sort'
    COMMIT = False
    TOOLTIP = _('Specify how this book should be sorted when by title.'
            ' For example, The Exorcist might be sorted as Exorcist, The.')
    LABEL = _('Title &sort:')

    def __init__(self, parent, title_edit, autogen_button):
        TitleEdit.__init__(self, parent)
        self.title_edit = title_edit

        base = self.TOOLTIP
        ok_tooltip = '<p>' + textwrap.fill(base+'<br><br>'+
                            _(' The green color indicates that the current '
                              'title sort matches the current title'))
        bad_tooltip = '<p>'+textwrap.fill(base + '<br><br>'+
                _(' The red color warns that the current '
                  'title sort does not match the current title. '
                  'No action is required if this is what you want.'))
        self.tooltips = (ok_tooltip, bad_tooltip)

        self.title_edit.textChanged.connect(self.update_state)
        self.textChanged.connect(self.update_state)

        autogen_button.clicked.connect(self.auto_generate)
        self.update_state()

    def update_state(self, *args):
        ts = title_sort(self.title_edit.current_val)
        normal = ts == self.current_val
        if normal:
            col = 'rgb(0, 255, 0, 20%)'
        else:
            col = 'rgb(255, 0, 0, 20%)'
        self.setStyleSheet('QLineEdit { color: black; '
                              'background-color: %s; }'%col)
        tt = self.tooltips[0 if normal else 1]
        self.setToolTip(tt)
        self.setWhatsThis(tt)

    def auto_generate(self, *args):
        self.current_val = title_sort(self.title_edit.current_val)

# }}}

# Authors {{{
class AuthorsEdit(MultiCompleteComboBox):

    TOOLTIP = ''
    LABEL = _('&Author(s):')

    def __init__(self, parent):
        self.dialog = parent
        self.books_to_refresh = set([])
        MultiCompleteComboBox.__init__(self, parent)
        self.setToolTip(self.TOOLTIP)
        self.setWhatsThis(self.TOOLTIP)
        self.setEditable(True)
        self.setSizeAdjustPolicy(self.AdjustToMinimumContentsLengthWithIcon)

    def get_default(self):
        return _('Unknown')

    def initialize(self, db, id_):
        self.books_to_refresh = set([])
        all_authors = db.all_authors()
        all_authors.sort(key=lambda x : sort_key(x[1]))
        self.clear()
        for i in all_authors:
            id, name = i
            name = [name.strip().replace('|', ',') for n in name.split(',')]
            self.addItem(authors_to_string(name))

        self.set_separator('&')
        self.set_space_before_sep(True)
        self.set_add_separator(tweaks['authors_completer_append_separator'])
        self.update_items_cache(db.all_author_names())

        au = db.authors(id_, index_is_id=True)
        if not au:
            au = _('Unknown')
        self.current_val = [a.strip().replace('|', ',') for a in au.split(',')]
        self.original_val = self.current_val

    def commit(self, db, id_):
        authors = self.current_val
        self.books_to_refresh |= db.set_authors(id_, authors, notify=False,
                allow_case_change=True)
        return True

    @dynamic_property
    def current_val(self):

        def fget(self):
            au = unicode(self.text()).strip()
            if not au:
                au = self.get_default()
            return string_to_authors(au)

        def fset(self, val):
            if not val:
                val = [self.get_default()]
            self.setEditText(' & '.join([x.strip() for x in val]))
            self.lineEdit().setCursorPosition(0)


        return property(fget=fget, fset=fset)

class AuthorSortEdit(EnLineEdit):

    TOOLTIP = _('Specify how the author(s) of this book should be sorted. '
            'For example Charles Dickens should be sorted as Dickens, '
            'Charles.\nIf the box is colored green, then text matches '
            'the individual author\'s sort strings. If it is colored '
            'red, then the authors and this text do not match.')
    LABEL = _('Author s&ort:')

    def __init__(self, parent, authors_edit, autogen_button, db,
            copy_a_to_as_action, copy_as_to_a_action):
        EnLineEdit.__init__(self, parent)
        self.authors_edit = authors_edit
        self.db = db

        base = self.TOOLTIP
        ok_tooltip = '<p>' + textwrap.fill(base+'<br><br>'+
                _(' The green color indicates that the current '
                    'author sort matches the current author'))
        bad_tooltip = '<p>'+textwrap.fill(base + '<br><br>'+
                _(' The red color indicates that the current '
                    'author sort does not match the current author. '
                    'No action is required if this is what you want.'))
        self.tooltips = (ok_tooltip, bad_tooltip)

        self.authors_edit.editTextChanged.connect(self.update_state)
        self.textChanged.connect(self.update_state)

        autogen_button.clicked.connect(self.auto_generate)
        copy_a_to_as_action.triggered.connect(self.auto_generate)
        copy_as_to_a_action.triggered.connect(self.copy_to_authors)
        self.update_state()

    @dynamic_property
    def current_val(self):

        def fget(self):
            return unicode(self.text()).strip()

        def fset(self, val):
            if not val:
                val = ''
            self.setText(val.strip())
            self.setCursorPosition(0)

        return property(fget=fget, fset=fset)

    def update_state(self, *args):
        au = unicode(self.authors_edit.text())
        au = re.sub(r'\s+et al\.$', '', au)
        au = self.db.author_sort_from_authors(string_to_authors(au))

        normal = au == self.current_val
        if normal:
            col = 'rgb(0, 255, 0, 20%)'
        else:
            col = 'rgb(255, 0, 0, 20%)'
        self.setStyleSheet('QLineEdit { color: black; '
                              'background-color: %s; }'%col)
        tt = self.tooltips[0 if normal else 1]
        self.setToolTip(tt)
        self.setWhatsThis(tt)

    def copy_to_authors(self):
        aus = self.current_val
        if aus:
            ln, _, rest = aus.partition(',')
            if rest:
                au = rest.strip() + ' ' + ln.strip()
                self.authors_edit.current_val = [au]

    def auto_generate(self, *args):
        au = unicode(self.authors_edit.text())
        au = re.sub(r'\s+et al\.$', '', au)
        authors = string_to_authors(au)
        self.current_val = self.db.author_sort_from_authors(authors)

    def initialize(self, db, id_):
        self.current_val = db.author_sort(id_, index_is_id=True)

    def commit(self, db, id_):
        aus = self.current_val
        db.set_author_sort(id_, aus, notify=False, commit=False)
        return True

# }}}

# Series {{{
class SeriesEdit(MultiCompleteComboBox):

    TOOLTIP = _('List of known series. You can add new series.')
    LABEL = _('&Series:')

    def __init__(self, parent):
        MultiCompleteComboBox.__init__(self, parent)
        self.set_separator(None)
        self.dialog = parent
        self.setSizeAdjustPolicy(
                self.AdjustToMinimumContentsLengthWithIcon)
        self.setToolTip(self.TOOLTIP)
        self.setWhatsThis(self.TOOLTIP)
        self.setEditable(True)
        self.books_to_refresh = set([])

    @dynamic_property
    def current_val(self):

        def fget(self):
            return unicode(self.currentText()).strip()

        def fset(self, val):
            if not val:
                val = ''
            self.setEditText(val.strip())
            self.lineEdit().setCursorPosition(0)

        return property(fget=fget, fset=fset)

    def initialize(self, db, id_):
        self.books_to_refresh = set([])
        all_series = db.all_series()
        all_series.sort(key=lambda x : sort_key(x[1]))
        self.update_items_cache([x[1] for x in all_series])
        series_id = db.series_id(id_, index_is_id=True)
        idx, c = None, 0
        self.clear()
        for i in all_series:
            id, name = i
            if id == series_id:
                idx = c
            self.addItem(name)
            c += 1

        self.lineEdit().setText('')
        if idx is not None:
            self.setCurrentIndex(idx)
        self.original_val = self.current_val

    def commit(self, db, id_):
        series = self.current_val
        self.books_to_refresh |= db.set_series(id_, series, notify=False,
                                            commit=True, allow_case_change=True)
        return True

class SeriesIndexEdit(QDoubleSpinBox):

    TOOLTIP = ''
    LABEL = _('&Number:')

    def __init__(self, parent, series_edit):
        QDoubleSpinBox.__init__(self, parent)
        self.dialog = parent
        self.db = self.original_series_name = None
        self.setMaximum(10000000)
        self.series_edit = series_edit
        series_edit.currentIndexChanged.connect(self.enable)
        series_edit.editTextChanged.connect(self.enable)
        series_edit.lineEdit().editingFinished.connect(self.increment)
        self.enable()

    def enable(self, *args):
        self.setEnabled(bool(self.series_edit.current_val))

    @dynamic_property
    def current_val(self):

        def fget(self):
            return self.value()

        def fset(self, val):
            if val is None:
                val = 1.0
            val = float(val)
            self.setValue(val)

        return property(fget=fget, fset=fset)

    def initialize(self, db, id_):
        self.db = db
        if self.series_edit.current_val:
            val = db.series_index(id_, index_is_id=True)
        else:
            val = 1.0
        self.current_val = val
        self.original_val = self.current_val
        self.original_series_name = self.series_edit.original_val

    def commit(self, db, id_):
        db.set_series_index(id_, self.current_val, notify=False, commit=False)
        return True

    def increment(self):
        if self.db is not None:
            try:
                series = self.series_edit.current_val
                if series and series != self.original_series_name:
                    ns = 1.0
                    if tweaks['series_index_auto_increment'] != 'const':
                        ns = self.db.get_next_series_num_for(series)
                    self.current_val = ns
                    self.original_series_name = series
            except:
                import traceback
                traceback.print_exc()


# }}}

class BuddyLabel(QLabel): # {{{

    def __init__(self, buddy):
        QLabel.__init__(self, buddy.LABEL)
        self.setBuddy(buddy)
        self.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
# }}}

class Format(QListWidgetItem): # {{{

    def __init__(self, parent, ext, size, path=None, timestamp=None):
        self.path = path
        self.ext = ext
        self.size = float(size)/(1024*1024)
        text = '%s (%.2f MB)'%(self.ext.upper(), self.size)
        QListWidgetItem.__init__(self, file_icon_provider().icon_from_ext(ext),
                                 text, parent, QListWidgetItem.UserType)
        if timestamp is not None:
            ts = timestamp.astimezone(local_tz)
            t = strftime('%a, %d %b %Y [%H:%M:%S]', ts.timetuple())
            text = _('Last modified: %s\n\nDouble click to view')%t
            self.setToolTip(text)
            self.setStatusTip(text)

# }}}

class FormatsManager(QWidget): # {{{

    def __init__(self, parent):
        QWidget.__init__(self, parent)
        self.dialog = parent
        self.changed = False

        self.l = l = QGridLayout()
        self.setLayout(l)
        self.cover_from_format_button = QToolButton(self)
        self.cover_from_format_button.setToolTip(
                _('Set the cover for the book from the selected format'))
        self.cover_from_format_button.setIcon(QIcon(I('book.png')))
        self.cover_from_format_button.setIconSize(QSize(32, 32))

        self.metadata_from_format_button = QToolButton(self)
        self.metadata_from_format_button.setIcon(QIcon(I('edit_input.png')))
        self.metadata_from_format_button.setIconSize(QSize(32, 32))

        self.add_format_button = QToolButton(self)
        self.add_format_button.setIcon(QIcon(I('add_book.png')))
        self.add_format_button.setIconSize(QSize(32, 32))
        self.add_format_button.clicked.connect(self.add_format)

        self.remove_format_button = QToolButton(self)
        self.remove_format_button.setIcon(QIcon(I('trash.png')))
        self.remove_format_button.setIconSize(QSize(32, 32))
        self.remove_format_button.clicked.connect(self.remove_format)

        self.formats = FormatList(self)
        self.formats.setAcceptDrops(True)
        self.formats.formats_dropped.connect(self.formats_dropped)
        self.formats.delete_format.connect(self.remove_format)
        self.formats.itemDoubleClicked.connect(self.show_format)
        self.formats.setDragDropMode(self.formats.DropOnly)
        self.formats.setIconSize(QSize(32, 32))
        self.formats.setMaximumWidth(200)

        l.addWidget(self.cover_from_format_button,    0, 0, 1, 1)
        l.addWidget(self.metadata_from_format_button, 2, 0, 1, 1)
        l.addWidget(self.add_format_button,           0, 2, 1, 1)
        l.addWidget(self.remove_format_button,        2, 2, 1, 1)
        l.addWidget(self.formats,                     0, 1, 3, 1)



    def initialize(self, db, id_):
        self.changed = False
        self.formats.clear()
        exts = db.formats(id_, index_is_id=True)
        self.original_val = set([])
        if exts:
            exts = exts.split(',')
            for ext in exts:
                if not ext:
                    ext = ''
                size = db.sizeof_format(id_, ext, index_is_id=True)
                timestamp = db.format_last_modified(id_, ext)
                if size is None:
                    continue
                Format(self.formats, ext, size, timestamp=timestamp)
                self.original_val.add(ext.lower())

    def commit(self, db, id_):
        if not self.changed:
            return True
        old_extensions, new_extensions, paths = set(), set(), {}
        for row in range(self.formats.count()):
            fmt = self.formats.item(row)
            ext, path = fmt.ext.lower(), fmt.path
            if 'unknown' in ext.lower():
                ext = None
            if path:
                new_extensions.add(ext)
                paths[ext] = path
            else:
                old_extensions.add(ext)
        for ext in new_extensions:
            db.add_format(id_, ext, open(paths[ext], 'rb'), notify=False,
                    index_is_id=True)
        dbfmts = db.formats(id_, index_is_id=True)
        db_extensions = set([f.lower() for f in (dbfmts.split(',') if dbfmts
            else [])])
        extensions = new_extensions.union(old_extensions)
        for ext in db_extensions:
            if ext not in extensions and ext in self.original_val:
                db.remove_format(id_, ext, notify=False, index_is_id=True)

        self.changed = False
        return True

    def add_format(self, *args):
        files = choose_files(self, 'add formats dialog',
                             _("Choose formats for ") +
                             self.dialog.title.current_val,
                             [(_('Books'), BOOK_EXTENSIONS)])
        self._add_formats(files)

    def _add_formats(self, paths):
        added = False
        if not paths:
            return added
        bad_perms = []
        for _file in paths:
            _file = os.path.abspath(_file)
            if not os.access(_file, os.R_OK):
                bad_perms.append(_file)
                continue

            nfile = run_plugins_on_import(_file)
            if nfile is not None:
                _file = nfile
            stat = os.stat(_file)
            size = stat.st_size
            ext = os.path.splitext(_file)[1].lower().replace('.', '')
            timestamp = utcfromtimestamp(stat.st_mtime)
            for row in range(self.formats.count()):
                fmt = self.formats.item(row)
                if fmt.ext.lower() == ext:
                    self.formats.takeItem(row)
                    break
            Format(self.formats, ext, size, path=_file, timestamp=timestamp)
            self.changed = True
            added = True
        if bad_perms:
            error_dialog(self, _('No permission'),
                    _('You do not have '
                'permission to read the following files:'),
                det_msg='\n'.join(bad_perms), show=True)

        return added

    def formats_dropped(self, event, paths):
        if self._add_formats(paths):
            event.accept()

    def remove_format(self, *args):
        rows = self.formats.selectionModel().selectedRows(0)
        for row in rows:
            self.formats.takeItem(row.row())
            self.changed = True

    def show_format(self, item, *args):
        self.dialog.do_view_format(item.path, item.ext)

    def get_selected_format_metadata(self, db, id_):
        old = prefs['read_file_metadata']
        if not old:
            prefs['read_file_metadata'] = True
        try:
            row = self.formats.currentRow()
            fmt = self.formats.item(row)
            if fmt is None:
                if self.formats.count() == 1:
                    fmt = self.formats.item(0)
                if fmt is None:
                    error_dialog(self, _('No format selected'),
                        _('No format selected')).exec_()
                    return None, None
            ext = fmt.ext.lower()
            if fmt.path is None:
                stream = db.format(id_, ext, as_file=True, index_is_id=True)
            else:
                stream = open(fmt.path, 'r+b')
            try:
                mi = get_metadata(stream, ext)
                return mi, ext
            except:
                error_dialog(self, _('Could not read metadata'),
                            _('Could not read metadata from %s format')%ext).exec_()
            return None, None
        finally:
            if old != prefs['read_file_metadata']:
                prefs['read_file_metadata'] = old

# }}}

class Cover(ImageView): # {{{

    download_cover = pyqtSignal()

    def __init__(self, parent):
        ImageView.__init__(self, parent)
        self.dialog = parent
        self._cdata = None
        self.cover_changed.connect(self.set_pixmap_from_data)

        self.select_cover_button = QPushButton(QIcon(I('document_open.png')),
                _('&Browse'), parent)
        self.trim_cover_button = QPushButton(QIcon(I('trim.png')),
                _('T&rim'), parent)
        self.remove_cover_button = QPushButton(QIcon(I('trash.png')),
            _('&Remove'), parent)

        self.select_cover_button.clicked.connect(self.select_cover)
        self.remove_cover_button.clicked.connect(self.remove_cover)
        self.trim_cover_button.clicked.connect(self.trim_cover)

        self.download_cover_button = QPushButton(_('Download co&ver'), parent)
        self.generate_cover_button = QPushButton(_('&Generate cover'), parent)

        self.download_cover_button.clicked.connect(self.download_cover)
        self.generate_cover_button.clicked.connect(self.generate_cover)

        self.buttons = [self.select_cover_button, self.remove_cover_button,
                self.trim_cover_button, self.download_cover_button,
                self.generate_cover_button]

        self.frame_size = (300, 400)
        self.setSizePolicy(QSizePolicy(QSizePolicy.Preferred,
            QSizePolicy.Preferred))

    def frame_resized(self, ev):
        sz = ev.size()
        self.frame_size = (sz.width()//3, sz.height())

    def sizeHint(self):
        sz = ImageView.sizeHint(self)
        w, h = sz.width(), sz.height()
        resized, nw, nh = fit_image(w, h, self.frame_size[0],
                self.frame_size[1])
        if resized:
            sz = QSize(nw, nh)
        return sz

    def select_cover(self, *args):
        files = choose_images(self, 'change cover dialog',
                             _('Choose cover for ') +
                             self.dialog.title.current_val)
        if not files:
            return
        _file = files[0]
        if _file:
            _file = os.path.abspath(_file)
            if not os.access(_file, os.R_OK):
                d = error_dialog(self, _('Cannot read'),
                        _('You do not have permission to read the file: ') + _file)
                d.exec_()
                return
            cf, cover = None, None
            try:
                cf = open(_file, "rb")
                cover = cf.read()
            except IOError as e:
                d = error_dialog(self, _('Error reading file'),
                        _("<p>There was an error reading from file: <br /><b>")
                        + _file + "</b></p><br />"+str(e))
                d.exec_()
            if cover:
                orig = self.current_val
                self.current_val = cover
                if self.current_val is None:
                    self.current_val = orig
                    error_dialog(self,
                        _("Not a valid picture"),
                            _file + _(" is not a valid picture"), show=True)

    def remove_cover(self, *args):
        self.current_val = None

    def trim_cover(self, *args):
        from calibre.utils.magick import Image
        cdata = self.current_val
        if not cdata:
            return
        im = Image()
        im.load(cdata)
        im.trim(10)
        cdata = im.export('png')
        self.current_val = cdata

    def generate_cover(self, *args):
        from calibre.ebooks import calibre_cover
        from calibre.ebooks.metadata import fmt_sidx
        from calibre.gui2 import config
        title = self.dialog.title.current_val
        author = authors_to_string(self.dialog.authors.current_val)
        if not title or not author:
            return error_dialog(self, _('Specify title and author'),
                    _('You must specify a title and author before generating '
                        'a cover'), show=True)
        series = self.dialog.series.current_val
        series_string = None
        if series:
            series_string = _('Book %s of %s')%(
                    fmt_sidx(self.dialog.series_index.current_val,
                    use_roman=config['use_roman_numerals_for_series_number']), series)
        self.current_val = calibre_cover(title, author,
                series_string=series_string)

    def set_pixmap_from_data(self, data):
        if not data:
            self.current_val = None
            return
        orig = self.current_val
        self.current_val = data
        if self.current_val is None:
            error_dialog(self, _('Invalid cover'),
                    _('Could not change cover as the image is invalid.'),
                    show=True)
            self.current_val = orig

    def initialize(self, db, id_):
        self._cdata = None
        self.current_val = db.cover(id_, index_is_id=True)
        self.original_val = self.current_val

    @property
    def changed(self):
        return self.current_val != self.original_val

    @dynamic_property
    def current_val(self):
        def fget(self):
            return self._cdata
        def fset(self, cdata):
            self._cdata = None
            pm = QPixmap()
            if cdata:
                pm.loadFromData(cdata)
            if pm.isNull():
                pm = QPixmap(I('default_cover.png'))
            else:
                self._cdata = cdata
            self.setPixmap(pm)
            tt = _('This book has no cover')
            if self._cdata:
                tt = _('Cover size: %dx%d pixels') % \
                (pm.width(), pm.height())
            self.setToolTip(tt)

        return property(fget=fget, fset=fset)

    def commit(self, db, id_):
        if self.changed:
            if self.current_val:
                db.set_cover(id_, self.current_val, notify=False, commit=False)
            else:
                db.remove_cover(id_, notify=False, commit=False)
        return True

# }}}

class CommentsEdit(Editor): # {{{

    @dynamic_property
    def current_val(self):
        def fget(self):
            return self.html
        def fset(self, val):
            if not val or not val.strip():
                val = ''
            else:
                val = comments_to_html(val)
            self.html = val
        return property(fget=fget, fset=fset)

    def initialize(self, db, id_):
        self.current_val = db.comments(id_, index_is_id=True)
        self.original_val = self.current_val

    def commit(self, db, id_):
        db.set_comment(id_, self.current_val, notify=False, commit=False)
        return True
# }}}

class RatingEdit(QSpinBox): # {{{
    LABEL = _('&Rating:')
    TOOLTIP = _('Rating of this book. 0-5 stars')

    def __init__(self, parent):
        QSpinBox.__init__(self, parent)
        self.setToolTip(self.TOOLTIP)
        self.setWhatsThis(self.TOOLTIP)
        self.setMaximum(5)
        self.setSuffix(' ' + _('stars'))

    @dynamic_property
    def current_val(self):
        def fget(self):
            return self.value()
        def fset(self, val):
            if val is None:
                val = 0
            val = int(val)
            if val < 0:
                val = 0
            if val > 5:
                val = 5
            self.setValue(val)
        return property(fget=fget, fset=fset)

    def initialize(self, db, id_):
        val = db.rating(id_, index_is_id=True)
        if val > 0:
            val = int(val/2.)
        else:
            val = 0
        self.current_val = val
        self.original_val = self.current_val

    def commit(self, db, id_):
        db.set_rating(id_, 2*self.current_val, notify=False, commit=False)
        return True

# }}}

class TagsEdit(MultiCompleteLineEdit): # {{{
    LABEL = _('Ta&gs:')
    TOOLTIP = '<p>'+_('Tags categorize the book. This is particularly '
            'useful while searching. <br><br>They can be any words '
            'or phrases, separated by commas.')

    def __init__(self, parent):
        MultiCompleteLineEdit.__init__(self, parent)
        self.books_to_refresh = set([])
        self.setToolTip(self.TOOLTIP)
        self.setWhatsThis(self.TOOLTIP)

    @dynamic_property
    def current_val(self):
        def fget(self):
            return [x.strip() for x in unicode(self.text()).split(',')]
        def fset(self, val):
            if not val:
                val = []
            self.setText(', '.join([x.strip() for x in val]))
            self.setCursorPosition(0)
        return property(fget=fget, fset=fset)

    def initialize(self, db, id_):
        self.books_to_refresh = set([])
        tags = db.tags(id_, index_is_id=True)
        tags = tags.split(',') if tags else []
        self.current_val = tags
        self.all_items = db.all_tags()
        self.original_val = self.current_val

    @property
    def changed(self):
        return self.current_val != self.original_val

    def edit(self, db, id_):
        if self.changed:
            if question_dialog(self, _('Tags changed'),
                    _('You have changed the tags. In order to use the tags'
                       ' editor, you must either discard or apply these '
                       'changes. Apply changes?'), show_copy_button=False):
                self.commit(db, id_)
                db.commit()
                self.original_val = self.current_val
            else:
                self.current_val = self.original_val
        d = TagEditor(self, db, id_)
        if d.exec_() == TagEditor.Accepted:
            self.current_val = d.tags
            self.all_items = db.all_tags()


    def commit(self, db, id_):
        self.books_to_refresh |= db.set_tags(
                id_, self.current_val, notify=False, commit=False,
                allow_case_change=True)
        return True

# }}}

class IdentifiersEdit(QLineEdit): # {{{
    LABEL = _('I&ds:')
    BASE_TT = _('Edit the identifiers for this book. '
            'For example: \n\n%s')%(
            'isbn:1565927249, doi:10.1000/182, amazon:1565927249')

    def __init__(self, parent):
        QLineEdit.__init__(self, parent)
        self.pat = re.compile(r'[^0-9a-zA-Z]')
        self.textChanged.connect(self.validate)

    @dynamic_property
    def current_val(self):
        def fget(self):
            raw = unicode(self.text()).strip()
            parts = [x.strip() for x in raw.split(',')]
            ans = {}
            for x in parts:
                c = x.split(':')
                if len(c) == 2:
                    ans[c[0]] = c[1]
            return ans
        def fset(self, val):
            if not val:
                val = {}
            txt = ', '.join(['%s:%s'%(k, v) for k, v in val.iteritems()])
            self.setText(txt.strip())
            self.setCursorPosition(0)
        return property(fget=fget, fset=fset)

    def initialize(self, db, id_):
        self.current_val = db.get_identifiers(id_, index_is_id=True)
        self.original_val = self.current_val

    def commit(self, db, id_):
        if self.original_val != self.current_val:
            db.set_identifiers(id_, self.current_val, notify=False, commit=False)
        return True

    def validate(self, *args):
        identifiers = self.current_val
        isbn = identifiers.get('isbn', '')
        tt = self.BASE_TT
        extra = ''
        if not isbn:
            col = 'rgba(0,255,0,0%)'
        elif check_isbn(isbn) is not None:
            col = 'rgba(0,255,0,20%)'
            extra = '\n\n'+_('This ISBN number is valid')
        else:
            col = 'rgba(255,0,0,20%)'
            extra = '\n\n' + _('This ISBN number is invalid')
        self.setToolTip(tt+extra)
        self.setStyleSheet('QLineEdit { background-color: %s }'%col)

# }}}

class PublisherEdit(MultiCompleteComboBox): # {{{
    LABEL = _('&Publisher:')

    def __init__(self, parent):
        MultiCompleteComboBox.__init__(self, parent)
        self.set_separator(None)
        self.setSizeAdjustPolicy(
                self.AdjustToMinimumContentsLengthWithIcon)
        self.books_to_refresh = set([])

    @dynamic_property
    def current_val(self):

        def fget(self):
            return unicode(self.currentText()).strip()

        def fset(self, val):
            if not val:
                val = ''
            self.setEditText(val.strip())
            self.lineEdit().setCursorPosition(0)

        return property(fget=fget, fset=fset)

    def initialize(self, db, id_):
        self.books_to_refresh = set([])
        all_publishers = db.all_publishers()
        all_publishers.sort(key=lambda x : sort_key(x[1]))
        self.update_items_cache([x[1] for x in all_publishers])
        publisher_id = db.publisher_id(id_, index_is_id=True)
        idx = None
        self.clear()
        for i, x in enumerate(all_publishers):
            id_, name = x
            if id_ == publisher_id:
                idx = i
            self.addItem(name)

        self.setEditText('')
        if idx is not None:
            self.setCurrentIndex(idx)

    def commit(self, db, id_):
        self.books_to_refresh |= db.set_publisher(id_, self.current_val,
                            notify=False, commit=False, allow_case_change=True)
        return True

# }}}

class DateEdit(QDateEdit): # {{{

    TOOLTIP = ''
    LABEL = _('&Date:')
    FMT = 'd MMM yyyy'
    ATTR = 'timestamp'

    def __init__(self, parent):
        QDateEdit.__init__(self, parent)
        self.setToolTip(self.TOOLTIP)
        self.setWhatsThis(self.TOOLTIP)
        fmt = self.FMT
        if fmt is None:
            fmt = tweaks['gui_pubdate_display_format']
            if fmt is None:
                fmt = 'MMM yyyy'
        self.setDisplayFormat(fmt)
        self.setCalendarPopup(True)
        self.setMinimumDate(UNDEFINED_QDATE)
        self.setSpecialValueText(_('Undefined'))
        self.clear_button = QToolButton(parent)
        self.clear_button.setIcon(QIcon(I('trash.png')))
        self.clear_button.setToolTip(_('Clear date'))
        self.clear_button.clicked.connect(self.reset_date)

    def reset_date(self, *args):
        self.current_val = None

    @dynamic_property
    def current_val(self):
        def fget(self):
            return qt_to_dt(self.date())
        def fset(self, val):
            if val is None:
                val = UNDEFINED_DATE
            self.setDate(QDate(val.year, val.month, val.day))
        return property(fget=fget, fset=fset)

    def initialize(self, db, id_):
        self.current_val = getattr(db, self.ATTR)(id_, index_is_id=True)
        self.original_val = self.current_val

    def commit(self, db, id_):
        if self.changed:
            getattr(db, 'set_'+self.ATTR)(id_, self.current_val, commit=False,
                notify=False)
        return True

    @property
    def changed(self):
        o, c = self.original_val, self.current_val
        return o.year != c.year or o.month != c.month or o.day != c.day

class PubdateEdit(DateEdit):
    LABEL = _('Publishe&d:')
    FMT = None
    ATTR = 'pubdate'

# }}}
