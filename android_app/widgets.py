"""Consistent touch-sized controls for mobile feature forms."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.checkbox import CheckBox
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup


def column():
    box = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(6), size_hint_y=None)
    box.bind(minimum_height=box.setter('height'))
    return box


def label(text='', height=None):
    view = Label(text=str(text), size_hint_y=None, halign='left', valign='middle', font_size='14sp')
    view.bind(width=lambda w, size: setattr(w, 'text_size', (size, None)))
    if height: view.height = dp(height)
    else: view.bind(texture_size=lambda w, size: setattr(w, 'height', max(dp(30), size[1] + dp(10))))
    return view


def button(text, callback, height=48):
    view = Button(text=text, size_hint_y=None, height=dp(height), font_size='14sp', halign='center', valign='middle')
    view.bind(size=lambda w, size: setattr(w, 'text_size', (size[0]-dp(10), size[1])))
    view.bind(on_release=lambda *_: callback())
    return view


def row(*views):
    box = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
    for view in views: box.add_widget(view)
    return box


def field(box, title, text='', numeric=False):
    box.add_widget(label(title))
    view = TextInput(text=str(text), multiline=False, size_hint_y=None, height=dp(48),
                     input_filter='int' if numeric else None, font_size='15sp')
    box.add_widget(view)
    return view


def select(box, title, values, current=None):
    box.add_widget(label(title))
    view = Spinner(text=current if current is not None else (values[0] if values else '無資料'),
                   values=list(values), size_hint_y=None, height=dp(48), font_size='14sp')
    box.add_widget(view)
    return view


def check(box, title, value=False):
    view = CheckBox(active=bool(value), size_hint_x=None, width=dp(48))
    text = label(title); text.size_hint_y = 1
    box.add_widget(row(view, text))
    return view


def dialog(title, body, height=.92):
    scroll = ScrollView(do_scroll_x=False); scroll.add_widget(body)
    popup = Popup(title=title, content=scroll, size_hint=(.97, height))
    popup.open(); return popup


def confirm(title, text, callback):
    body = column(); body.add_widget(label(text))
    popup = None
    def run():
        callback(); popup.dismiss()
    body.add_widget(row(button('確認', run), button('取消', lambda: popup.dismiss())))
    popup = dialog(title, body, .65)
    return popup


def pick(title, entries, callback, icon=None):
    """Searchable paged choices; never builds an unbounded catalogue of widgets."""
    body = column(); search = field(body, '搜尋名稱／ID')
    results = column(); body.add_widget(results)
    state = {'offset': 0}; popup = None
    def choose(value): callback(value); popup.dismiss()
    def render(*_):
        results.clear_widgets()
        q = search.text.strip().casefold()
        matches = [(key, text) for key, text in entries if q in text.casefold()]
        pages = max(1, (len(matches)+11)//12)
        state['offset'] = max(0, min(state['offset'], pages-1))
        for key, text in matches[state['offset']*12:state['offset']*12+12]:
            choice = button(text, lambda k=key: choose(k), 60)
            if icon is not None:
                image = icon(key)
                results.add_widget(row(image, choice) if image is not None else choice)
            else: results.add_widget(choice)
        results.add_widget(label(f"{state['offset']+1}/{pages} 頁 · {len(matches)} 項"))
        results.add_widget(row(button('上一頁', lambda: move(-1)), button('下一頁', lambda: move(1))))
    def move(delta): state['offset'] += delta; render()
    def find(*_): state['offset'] = 0; render()
    search.bind(text=find); render()
    body.add_widget(button('取消', lambda: popup.dismiss()))
    popup = dialog(title, body)
    return popup
