"""Match salary inflows to clients by match_text."""
from datetime import date
from types import SimpleNamespace
from unittest import TestCase

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase as DjangoTestCase

from core.clients import match_client
from core.models import Client, Document, date_in_force


def _tx(**kwargs):
    defaults = {
        "amount": 1000,
        "counterparty": "",
        "concept": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class MatchClientTests(TestCase):
    def test_longest_match_wins(self):
        jko = SimpleNamespace(match_text="Jko Connect")
        guru = SimpleNamespace(match_text="Guruflow")
        tx = _tx(counterparty="Inmediata De Guruflow Team Ltd")
        self.assertIs(match_client([jko, guru], tx), guru)

    def test_ignores_expenses(self):
        client = SimpleNamespace(match_text="NETGURU")
        self.assertIsNone(match_client([client], _tx(amount=-10, counterparty="NETGURU S.A")))

    def test_netguru_and_blackthorn(self):
        netguru = SimpleNamespace(match_text="NETGURU")
        blackthorn = SimpleNamespace(match_text="Blackthorn")
        self.assertIs(
            match_client(
                [netguru, blackthorn],
                _tx(counterparty="1/blackthorn Ai Ltd 3/gb/london Ec1, Referencia:"),
            ),
            blackthorn,
        )
        self.assertIs(
            match_client([netguru, blackthorn], _tx(counterparty="Netguru S.a")),
            netguru,
        )


class ContractWindowTests(TestCase):
    def test_open_ended_after_start(self):
        on = date(2026, 9, 6)
        self.assertTrue(date_in_force(date(2026, 4, 1), None, on))
        self.assertFalse(date_in_force(date(2026, 10, 1), None, on))
        self.assertFalse(date_in_force(date(2026, 1, 26), date(2026, 3, 31), on))
        self.assertTrue(date_in_force(None, None, on))


class ClientActiveTests(DjangoTestCase):
    def test_contract_beats_engagement_window(self):
        user = get_user_model().objects.create_user("t", password="x")
        client = Client.objects.create(
            owner=user,
            name="Guruflow Team Ltd",
            active_from=date(2026, 1, 1),
            active_to=None,
        )
        self.assertTrue(client.is_active(date(2026, 9, 6)))
        Document.objects.create(
            owner=user,
            client=client,
            kind=Document.KIND_AGREEMENT,
            title="Pin-Up",
            document_date=date(2024, 10, 1),
            starts_on=date(2024, 10, 1),
            ends_on=date(2025, 5, 31),
            file=ContentFile(b"%PDF", name="pinup.pdf"),
        )
        client = Client.objects.prefetch_related("documents").get(pk=client.pk)
        self.assertFalse(client.is_active(date(2026, 9, 6)))
        self.assertTrue(client.is_active(date(2025, 3, 1)))


class DocumentUploadTests(DjangoTestCase):
    def test_spooled_file_does_not_crash_empty_fields(self):
        from django.core.files.uploadedfile import TemporaryUploadedFile
        from django.utils.datastructures import MultiValueDict
        from rest_framework.test import APIRequestFactory, force_authenticate

        from core.serializers import DocumentSerializer

        user = get_user_model().objects.create_user("u", password="x")
        tmp = TemporaryUploadedFile("policy.pdf", "application/pdf", 10, "utf-8")
        tmp.file.write(b"%PDF-1.4 x")
        tmp.seek(0)
        data = MultiValueDict(
            {
                "kind": ["other"],
                "title": ["Policy schedule"],
                "client": [""],
                "document_date": [""],
                "starts_on": [""],
                "ends_on": [""],
                "file": [tmp],
            }
        )
        req = APIRequestFactory().post("/api/documents/")
        force_authenticate(req, user=user)
        ser = DocumentSerializer(data=data, context={"request": req})
        self.assertTrue(ser.is_valid(), ser.errors)
