from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.models import ContractsAppeared, IgkStatData, SystemEvent, ZnpData, ZnpDataSAP


class SeedDemoTests(TestCase):
    def test_seed_loads_everything(self):
        call_command("seed_demo", "--contracts", "20", stdout=StringIO())
        self.assertGreater(IgkStatData.objects.count(), 20)
        self.assertTrue(ZnpData.objects.exists())
        self.assertTrue(ZnpData.objects.filter(parent__isnull=False).exists())
        self.assertTrue(ZnpDataSAP.objects.exists())
        self.assertTrue(ContractsAppeared.objects.exists())
        self.assertEqual(
            set(SystemEvent.objects.values_list("event_key", flat=True)),
            {"contracts_load", "znp_load", "sap_load"},
        )
