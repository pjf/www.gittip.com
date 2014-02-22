from __future__ import unicode_literals

import os

import balanced
import mock
import vcr

from gittip import billing
from gittip.security import authentication
from gittip.testing import Harness
from gittip.models.participant import Participant


def setUp_balanced(o):
    o.vcr = vcr.VCR(
        cassette_library_dir = os.path.dirname(os.path.realpath(__file__)) + '/fixtures/',
        record_mode = 'once',
        match_on = ['url', 'method'],
    )
    #o.vcr_cassette = o.vcr.use_cassette('{}.yml'.format(o.__name__)).__enter__()
    o.balanced_marketplace = balanced.Marketplace.my_marketplace


def setUp_balanced_resources(o):
    o.balanced_customer_href = unicode(balanced.Customer().save().href)
    o.card_href = unicode(balanced.Card(
        number='4111111111111111',
        expiration_month=10,
        expiration_year=2020,
        address={
            'line1': "123 Main Street",
            'state': 'Confusion',
            'postal_code': '90210',
        },
        # gittip stores some of the address data in the meta fields,
        # continue using them to support backwards compatibility
        meta={
            'address_2': 'Box 2',
            'city_town': '',
            'region': 'Confusion',
        }
    ).save().href)
    o.bank_account_href = unicode(balanced.BankAccount(
        name='Homer Jay',
        account_number='112233a',
        routing_number='121042882',
    ).save().href)


def tearDown_balanced(o):
    pass
    #o.vcr_cassette.__exit__(None, None, None)


class TestBillingBase(Harness):

    @classmethod
    def setUpClass(cls):
        super(TestBillingBase, cls).setUpClass()
        setUp_balanced(cls)

    @classmethod
    def tearDownClass(cls):
        tearDown_balanced(cls)
        super(TestBillingBase, cls).tearDownClass()

    def setUp(self):
        Harness.setUp(self)
        setUp_balanced_resources(self)
        self.alice = self.make_participant('alice', elsewhere='github')


class TestBalancedCard(Harness):

    @classmethod
    def setUpClass(cls):
        super(TestBalancedCard, cls).setUpClass()
        setUp_balanced(cls)

    def setUp(self):
        Harness.setUp(self)
        setUp_balanced_resources(self)

    @classmethod
    def tearDownClass(cls):
        tearDown_balanced(cls)
        super(TestBalancedCard, cls).tearDownClass()

    def test_balanced_card_basically_works(self):
        balanced.Card.fetch(self.card_href) \
                     .associate_to_customer(self.balanced_customer_href)

        expected = {
            'id': self.balanced_customer_href,
            'last_four': 'xxxxxxxxxxxx1111',
            'last4': 'xxxxxxxxxxxx1111',
            'expiration_month': 10,
            'expiration_year': 2020,
            'address_1': '123 Main Street',
            'address_2': 'Box 2',
            'state': 'Confusion',
            'zip': '90210',
        }
        card = billing.BalancedCard(self.balanced_customer_href)
        actual = dict([(name, card[name]) for name in expected])
        assert actual == expected

    @mock.patch('balanced.Customer')
    def test_balanced_card_gives_class_name_instead_of_KeyError(self, ba):
        card = mock.Mock()

        balanced_account = ba.fetch.return_value
        balanced_account.href = self.balanced_customer_href
        balanced_account.cards = mock.Mock()
        balanced_account.cards.filter.return_value.all.return_value = [card]

        card = billing.BalancedCard(self.balanced_customer_href)

        expected = mock.Mock.__name__
        actual = card['nothing'].__class__.__name__

        assert actual == expected

    def test_balanced_works_with_old_urls(self):
        # gittip will have a combination of old style from v1
        # and new urls from v1.1
        balanced.Card.fetch(self.card_href).associate_to_customer(
            self.balanced_customer_href
        )
        # do not actually do this in any real system
        # but construct the url using the id from the
        # customer and marketplace on the new api
        # to match the format of that of the old one
        url_user = '/v1/marketplaces/{}/accounts/{}'.format(
            self.balanced_marketplace.id,
            self.balanced_customer_href.split('/customers/')[1])

        card = billing.BalancedCard(url_user)

        assert card._thing.href == self.card_href


class TestStripeCard(Harness):
    @mock.patch('stripe.Customer')
    def test_stripe_card_basically_works(self, sc):
        active_card = {}
        active_card['last4'] = '1234'
        active_card['expiration_month'] = 10
        active_card['expiration_year'] = 2020
        active_card['address_line1'] = "123 Main Street"
        active_card['address_line2'] = "Box 2"
        active_card['address_state'] = "Confusion"
        active_card['address_zip'] = "90210"

        stripe_customer = sc.retrieve.return_value
        stripe_customer.id = 'deadbeef'
        stripe_customer.get = {'active_card': active_card}.get

        expected = {
            'id': 'deadbeef',
            'last4': '************1234',
            'expiration_month': 10,
            'expiration_year': 2020,
            'address_1': '123 Main Street',
            'address_2': 'Box 2',
            'state': 'Confusion',
            'zip': '90210'
        }
        card = billing.StripeCard('deadbeef')
        actual = dict([(name, card[name]) for name in expected])
        assert actual == expected

    @mock.patch('stripe.Customer')
    def test_stripe_card_gives_empty_string_instead_of_KeyError(self, sc):
        stripe_customer = sc.retrieve.return_value
        stripe_customer.id = 'deadbeef'
        stripe_customer.get = {'active_card': {}}.get

        expected = ''
        actual = billing.StripeCard('deadbeef')['nothing']
        assert actual == expected


class TestBalancedBankAccount(Harness):

    @classmethod
    def setUpClass(cls):
        super(TestBalancedBankAccount, cls).setUpClass()
        setUp_balanced(cls)

    def setUp(self):
        Harness.setUp(self)
        setUp_balanced_resources(self)

    @classmethod
    def tearDownClass(cls):
        tearDown_balanced(cls)
        super(TestBalancedBankAccount, cls).tearDownClass()


    def test_balanced_bank_account(self):
        balanced.BankAccount.fetch(self.bank_account_href)\
                            .associate_to_customer(self.balanced_customer_href)

        ba_account = billing.BalancedBankAccount(self.balanced_customer_href)

        assert ba_account.is_setup

        with self.assertRaises(IndexError):
            ba_account.__getitem__('invalid')

        actual = ba_account['customer_href']
        expected = self.balanced_customer_href
        assert actual == expected

    def test_balanced_bank_account_not_setup(self):
        bank_account = billing.BalancedBankAccount(None)
        assert not bank_account.is_setup
        assert not bank_account['id']


class TestBalancedExternalAccount(Harness):
    """Tests related to processing coinbase transactions"""

    @classmethod
    def setUpClass(cls):
        super(TestBalancedExternalAccount, cls).setUpClass()
        setUp_balanced(cls)

    def setUp(self):
        Harness.setUp(self)
        setUp_balanced_resources(self)

    @classmethod
    def tearDownClass(cls):
        tearDown_balanced(cls)
        super(TestBalancedExternalAccount, cls).tearDownClass()

    def test_balanced_external_account(self):
        ea = balanced.ExternalAccount(
            token='123123123',
            provider='test'
        ).save()
        ea.associate_to_customer(self.balanced_customer_href)

        ea_account = billing.BalancedExternalAccount(self.balanced_customer_href)

        assert ea_account['customer_href'] == self.balanced_customer_href



class TestBillingAssociate(TestBillingBase):

    def test_associate_valid_card(self):
        billing.associate(self.db, u"credit card", 'alice', None, self.card_href)

        user = authentication.User.from_username('alice')
        customer = balanced.Customer.fetch(user.participant.balanced_account_uri)
        cards = customer.cards.all()
        assert len(cards) == 1
        assert cards[0].href == self.card_href

    def test_associate_invalid_card(self): #, find):

        billing.associate( self.db
                         , u"credit card"
                         , 'alice'
                         , self.balanced_customer_href
                         , '/cards/CC123123123123',  # invalid href
                          )
        user = authentication.User.from_username('alice')
        # participant in db should be updated to reflect the error message of
        # last update
        assert user.participant.last_bill_result == '404 Client Error: NOT FOUND'

    def test_associate_bank_account_valid(self):

        billing.associate( self.db
                         , u"bank account"
                         , 'alice'
                         , self.balanced_customer_href
                         , self.bank_account_href
                          )

        #args, _ = find.call_args

        customer = balanced.Customer.fetch(self.balanced_customer_href)
        bank_accounts = customer.bank_accounts.all()
        assert len(bank_accounts) == 1
        assert bank_accounts[0].href == self.bank_account_href


        user = authentication.User.from_username('alice')

        # participant in db should be updated
        assert user.participant.last_ach_result == ''

    def test_associate_bank_account_invalid(self):

        billing.associate( self.db
                         , u"bank account"
                         , 'alice'
                         , self.balanced_customer_href
                         , '/bank_accounts/BA123123123123123123' # invalid href
                          )

        # participant in db should be updated
        alice = Participant.from_username('alice')
        assert alice.last_ach_result == '404 Client Error: NOT FOUND'


class TestBillingClear(TestBillingBase):

    def test_clear(self):

        balanced.Card.fetch(self.card_href)\
                     .associate_to_customer(self.balanced_customer_href)

        MURKY = """\

            UPDATE participants
               SET balanced_account_uri='not null'
                 , last_bill_result='ooga booga'
             WHERE username=%s

        """
        self.db.run(MURKY, ('alice',))

        billing.clear(self.db, u"credit card", 'alice', self.balanced_customer_href)

        customer = balanced.Customer.fetch(self.balanced_customer_href)
        cards = customer.cards.all()
        assert len(cards) == 0

        user = authentication.User.from_username('alice')
        assert not user.participant.last_bill_result
        assert user.participant.balanced_account_uri

    def test_clear_bank_account(self):
        balanced.BankAccount.fetch(self.bank_account_href)\
                            .associate_to_customer(self.balanced_customer_href)

        MURKY = """\

            UPDATE participants
               SET balanced_account_uri='not null'
                 , last_ach_result='ooga booga'
             WHERE username=%s

        """
        self.db.run(MURKY, ('alice',))

        billing.clear(self.db, u"bank account", 'alice', self.balanced_customer_href)

        customer = balanced.Customer.fetch(self.balanced_customer_href)
        bank_accounts = customer.bank_accounts.all()
        assert len(bank_accounts) == 0

        user = authentication.User.from_username('alice')
        assert not user.participant.last_ach_result
        assert user.participant.balanced_account_uri


class TestBillingStoreError(TestBillingBase):
    def test_store_error_stores_bill_error(self):
        billing.store_error(self.db, u"credit card", "alice", "cheese is yummy")
        rec = self.db.one("select * from participants where "
                            "username='alice'")
        expected = "cheese is yummy"
        actual = rec.last_bill_result
        assert actual == expected

    def test_store_error_stores_ach_error(self):
        for message in ['cheese is yummy', 'cheese smells like my vibrams']:
            billing.store_error(self.db, u"bank account", 'alice', message)
            rec = self.db.one("select * from participants "
                                "where username='alice'")
            assert rec.last_ach_result == message
