# -*- coding: utf-8 -*-
# Cards and Deck classes

from game.autoenv import Game, GameError, sync_primitive, GameObject
import random
import logging
log = logging.getLogger('THBattle_Cards')

from utils import BatchList

from .. import actions


class Card(GameObject):
    NOTSET = 0
    SPADE = 1
    HEART = 2
    CLUB = 3
    DIAMOND = 4

    RED = 5
    BLACK = 6

    _color = None
    card_classes = {}

    def __init__(self, suit=NOTSET, number=0, resides_in=None):
        self.syncid = 0  # Deck will touch this
        self.suit = suit
        self.number = number
        self.resides_in = resides_in

    def __data__(self):
        return dict(
            type=self.__class__.__name__,
            suit=self.suit,
            number=self.number,
            syncid=self.syncid,
        )

    def __eq__(self, other):
        if not isinstance(other, Card): return False
        return self.syncid == other.syncid

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return 84065234 + self.syncid

    def sync(self, data):  # this only executes at client side, let it crash.
        if data['syncid'] != self.syncid:
            logging.error(
                'CardOOS: server: %s, %d, %d, syncid=%d; client: %s, %d, %d, syncid=%d',
                data['type'], data['suit'], data['number'], data['syncid'],
                self.__class__.__name__, self.suit, self.number, self.syncid,
            )
            raise GameError('Card: out of sync')

        clsname = data['type']
        cls = Card.card_classes.get(clsname)
        if not cls: raise GameError('Card: unknown card class')
        self.__class__ = cls
        self.suit = data['suit']
        self.number = data['number']

    def move_to(self, resides_in):
        try:
            self.resides_in.remove(self)
        except (AttributeError, ValueError):
            pass

        if resides_in is not None:
            resides_in.append(self)

        self.resides_in = resides_in

    def __repr__(self):
        return u'%s(%d, %d) at 0x%x' % (
            self.__class__.__name__, self.suit, self.number,
            id(self),
        )

    def is_card(self, cls):
        return isinstance(self, cls)

    @property
    def color(self):
        if self._color is not None: return self._color
        s = self.suit
        if s in (Card.HEART, Card.DIAMOND):
            return Card.RED
        elif s in (Card.SPADE, Card.CLUB):
            return Card.BLACK
        else:
            return Card.NOTSET

    @color.setter
    def color(self, val):
        self._color = val


class VirtualCard(Card):
    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__

    sort_index = 0
    syncid = 0

    def __init__(self, player):
        self.player = player
        self.suit = Card.NOTSET
        self.number = 0
        self.resides_in = player.special

    def __data__(self):
        return {
            'class': self.__class__.__name__,
            'syncid': self.syncid,
            'vcard': True,
        }

    def check(self): # override this
        return False

    @classmethod
    def unwrap(cls, vcard):
        l = []
        sl = vcard[:]
        while sl:
            s = sl.pop()
            try:
                sl.extend(s.associated_cards)
            except AttributeError:
                l.append(s)
        return l

    @classmethod
    def wrap(cls, cl, player):
        vc = cls(player)
        if not cl:
            vc.associated_cards = []
            return vc

        suit = cl[0].suit if len(cl) == 1 else Card.NOTSET

        color = set([c.color for c in cl])
        color = color.pop() if len(color) == 1 else Card.NOTSET

        num = set([c.number for c in cl])
        num = num.pop() if len(num) == 1 else Card.NOTSET

        vc.suit, vc.number, vc.color = suit, num, color
        vc.associated_cards = cl[:]
        return vc

    def sync(self, data):
        assert data['vcard']
        assert self.__class__.__name__ == data['class']
        assert self.syncid == data['syncid']

from collections import deque

class CardList(GameObject, deque):
    DECKCARD = 'deckcard'
    DROPPEDCARD = 'droppedcard'
    HANDCARD = 'handcard'
    SHOWNCARD = 'showncard'
    EQUIPS = 'equips'
    FATETELL = 'fatetell'
    SPECIAL = 'special'
    FAITHS = 'faiths'
    def __init__(self, owner, type):
        self.owner = owner
        self.type = type
        deque.__init__(self)

    def __repr__(self):
        return "CardList(owner=%s, type=%s, len == %d)" % (self.owner, self.type, len(self))


class Deck(GameObject):
    def __init__(self, card_definition=None):
        if not card_definition:
            from .definition import card_definition

        from weakref import WeakValueDictionary
        self.cards_record = {}
        self.vcards_record = WeakValueDictionary()
        self.droppedcards = CardList(None, 'droppedcard')
        self.special = CardList(None, 'special')
        cards = CardList(None, 'deckcard')
        self.cards = cards
        cards.extend(
            cls(suit, n, cards)
            for cls, suit, n in card_definition
        )
        self.shuffle(cards)

    def getcards(self, num):
        cl = self.cards
        if len(self.cards) <= num:
            dcl = self.droppedcards

            assert all(not c.is_card(VirtualCard) for c in dcl)
            l = [c.__class__(c.suit, c.number, cl) for c in dcl]
            dcl.clear()
            dcl.extend(l)
            self.shuffle(dcl)
            cl.extend(dcl)
            dcl.clear()

        cl = self.cards
        rst = []
        for i in xrange(min(len(cl), num)):
            rst.append(cl[i])

        return rst

    def lookupcards(self, idlist):
        l = []
        cr = self.cards_record
        vcr = self.vcards_record
        for cid in idlist:
            c = vcr.get(cid, None) or cr.get(cid, None)
            if c: l.append(c)

        return l

    def register_card(self, card):
        assert not card.syncid
        sid = Game.getgame().get_synctag()
        card.syncid = sid
        self.cards_record[sid] = card
        return sid

    def register_vcard(self, vc):
        sid = Game.getgame().get_synctag()
        vc.syncid = sid
        self.vcards_record[sid] = vc
        return sid

    def shuffle(self, cl):
        if Game.SERVER_SIDE:
            seed = long(Game.getgame().random.randint(1, 27814431486575L))
        else:
            seed = 0L

        owner = cl.owner
        seed = sync_primitive(seed, owner)

        if seed:  # cardlist owner & server
            shuffler = random.Random(seed)
            shuffler.shuffle(cl)
        else:  # others
            for c in cl:
                c.__class__ = HiddenCard
                c.suit = c.number = 0

        for c in cl:
            c.syncid = 0
            self.register_card(c)


class Skill(VirtualCard):
    category = ('skill', )

    def __init__(self, player):
        assert player is not None
        self.associated_cards = []
        VirtualCard.__init__(self, player)

    def check(self): # override this
        return False

    # target = xxx
    # associated_action = xxx
    # instance var: associated_cards = xxx


class TreatAsSkill(Skill):
    treat_as = None

    @property
    def category(self):
        return ('skill', ) + self.treat_as.category

    def check(self):
        return False

    def is_card(self, cls):
        if issubclass(self.treat_as, cls): return True
        return isinstance(self, cls)

    def __getattribute__(self, name):
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            tr = object.__getattribute__(self, 'treat_as')
            return getattr(tr, name)


# card targets:
@staticmethod
def t_None(g, source, tl):
    return (None, False)


@staticmethod
def t_Self(g, source, tl):
    return ([source], True)


@staticmethod
def t_OtherOne(g, source, tl):
    tl = [t for t in tl if not t.dead]
    try:
        tl.remove(source)
    except ValueError:
        pass
    return (tl[-1:], bool(len(tl)))


@staticmethod
def t_One(g, source, tl):
    tl = [t for t in tl if not t.dead]
    return (tl[-1:], bool(len(tl)))


@staticmethod
def t_All(g, source, tl):
    l = g.players.rotate_to(source)
    del l[0]
    return ([t for t in l if not t.dead], True)


@staticmethod
def t_AllInclusive(g, source, tl):
    l = g.players.rotate_to(source)
    return ([t for t in l if not t.dead], True)


def t_OtherLessEqThanN(n):
    @staticmethod
    def _t_OtherLessEqThanN(g, source, tl):
        tl = [t for t in tl if not t.dead]
        try:
            tl.remove(source)
        except ValueError:
            pass
        return (tl[:n], bool(len(tl)))
    return _t_OtherLessEqThanN


@staticmethod
def t_OneOrNone(g, source, tl):
    tl = [t for t in tl if not t.dead]
    return (tl[-1:], True)


def t_OtherN(n):
    @staticmethod
    def _t_OtherN(g, source, tl):
        tl = [t for t in tl if not t.dead]
        try:
            tl.remove(source)
        except ValueError:
            pass
        return (tl[:n], bool(len(tl) >= n))
    return _t_OtherN


class HiddenCard(Card):  # special thing....
    associated_action = None
    target = t_None
