from decimal import Decimal
from django.core.management import call_command
from django.test import TestCase
from store.models import Brand, Category, HardwareSpecProfile, Inventory, Product
from pc_builder.models import ChipsetCPUSupport, MotherboardCPUSupport
from pc_builder.services.compatibility import (
    CompatibilityEngine,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_UNKNOWN,
    STATUS_WARNING,
)


def _make_part(slot: str, name: str, price: str = '10000.00', **spec_fields) -> Product:
    cat, _ = Category.objects.get_or_create(
        component_slot=slot,
        defaults={
            'name': slot.title(),
            'slug': f'cat-{slot}',
            'is_pc_component': True,
        },
    )
    brand, _ = Brand.objects.get_or_create(name='TestBrand', slug='testbrand')
    slug = f'{slot}-{name.lower().replace(" ", "-")}-{Product.objects.count() + 1}'
    product = Product.objects.create(
        name=name,
        slug=slug,
        sku=f'TST-{Product.objects.count() + 1}',
        category=cat,
        brand=brand,
        price=Decimal(price),
        is_active=True,
        spec_verified=True,
    )
    Inventory.objects.create(product=product, quantity=10)
    if spec_fields:
        HardwareSpecProfile.objects.create(product=product, **spec_fields)
    return product


class DeterministicCompatibilityEngineTests(TestCase):
    def setUp(self):
        self.engine = CompatibilityEngine()

    def test_cpu_motherboard_socket_mismatch_is_incompatible(self):
        cpu = _make_part(
            'cpu', 'Ryzen 5 7600',
            socket='AM5', cpu_family='Ryzen 7000', tdp_watts=65,
            integrated_graphics=True, includes_stock_cooler=True,
            supported_memory_types=['DDR5'], max_memory_gb=128, max_memory_speed_mhz=5200,
        )
        mobo = _make_part(
            'motherboard', 'MSI B760M',
            socket='LGA1700', chipset='B760', form_factor='Micro-ATX',
            memory_type='DDR4', memory_slots=4, max_memory_gb=128,
            supported_cpu_families=['Intel 12th Gen', 'Intel 13th Gen'],
            m2_slots=2, m2_nvme_slots=2, sata_ports=4,
        )
        report = self.engine.evaluate_products({'cpu': cpu, 'motherboard': mobo})
        self.assertEqual(report.overall_status, STATUS_INCOMPATIBLE)
        self.assertTrue(any(c.rule_code == 'CPU_MOBO_SOCKET_MISMATCH' for c in report.incompatibilities))

    def test_matching_socket_am4_b550_rejects_ryzen_1000_via_chipset_matrix(self):
        ChipsetCPUSupport.objects.create(
            socket='AM4',
            chipset='B550',
            cpu_family='Ryzen 1000',
            status='incompatible',
            notes='AMD B550 officially drops Ryzen 1000 support despite AM4 socket.',
        )
        cpu = _make_part(
            'cpu', 'Ryzen 5 1400',
            socket='AM4', cpu_family='Ryzen 1000', tdp_watts=65,
            integrated_graphics=False, includes_stock_cooler=True,
            supported_memory_types=['DDR4'],
        )
        mobo = _make_part(
            'motherboard', 'MSI B550M PRO-VDH',
            socket='AM4', chipset='B550', form_factor='Micro-ATX',
            memory_type='DDR4', memory_slots=4, max_memory_gb=128,
            supported_cpu_families=['Ryzen 3000', 'Ryzen 4000G', 'Ryzen 5000'],
            m2_slots=2, m2_nvme_slots=2, sata_ports=4,
        )
        report = self.engine.evaluate_products({'cpu': cpu, 'motherboard': mobo})
        self.assertEqual(report.overall_status, STATUS_INCOMPATIBLE)
        self.assertTrue(any(c.rule_code == 'CPU_MOBO_CHIPSET_INCOMPATIBLE' for c in report.incompatibilities))

    def test_b450_ryzen_5000_triggers_bios_update_warning_not_silent_pass(self):
        ChipsetCPUSupport.objects.create(
            socket='AM4',
            chipset='B450',
            cpu_family='Ryzen 5000',
            status='bios_update_required',
            notes='B450 requires updated BIOS for Ryzen 5000 series.',
        )
        cpu = _make_part(
            'cpu', 'Ryzen 5 5600',
            socket='AM4', cpu_family='Ryzen 5000', tdp_watts=65,
            integrated_graphics=True, includes_stock_cooler=True,
            supported_memory_types=['DDR4'], max_memory_gb=128, max_memory_speed_mhz=3200,
        )
        mobo = _make_part(
            'motherboard', 'ASUS TUF B450M',
            socket='AM4', chipset='B450', form_factor='Micro-ATX',
            memory_type='DDR4', memory_slots=4, max_memory_gb=128,
            m2_slots=1, m2_nvme_slots=1, sata_ports=4,
        )
        report = self.engine.evaluate_products({'cpu': cpu, 'motherboard': mobo})
        self.assertEqual(report.overall_status, STATUS_WARNING)
        self.assertTrue(any(c.rule_code == 'CPU_MOBO_CHIPSET_BIOS_WARNING' for c in report.warnings))

    def test_motherboard_qvl_override_takes_precedence(self):
        cpu = _make_part('cpu', 'Ryzen Custom', socket='AM4', cpu_family='Ryzen 3000', tdp_watts=65, integrated_graphics=True, includes_stock_cooler=True)
        mobo = _make_part('motherboard', 'Board QVL Test', socket='AM4', chipset='X570', memory_type='DDR4', memory_slots=4, max_memory_gb=128)
        MotherboardCPUSupport.objects.create(motherboard=mobo, cpu=cpu, status='unsupported', notes='Explicitly excluded from QVL.')
        report = self.engine.evaluate_products({'cpu': cpu, 'motherboard': mobo})
        self.assertEqual(report.overall_status, STATUS_INCOMPATIBLE)
        self.assertTrue(any(c.rule_code == 'CPU_MOBO_QVL_UNSUPPORTED' for c in report.incompatibilities))

    def test_am5_motherboard_with_ddr4_ram_is_incompatible(self):
        cpu = _make_part(
            'cpu', 'Ryzen 5 7600',
            socket='AM5', cpu_family='Ryzen 7000', tdp_watts=65,
            integrated_graphics=True, includes_stock_cooler=True,
            supported_memory_types=['DDR5'], max_memory_gb=128, max_memory_speed_mhz=5200,
        )
        mobo = _make_part(
            'motherboard', 'MSI PRO B650M-P',
            socket='AM5', chipset='B650', form_factor='Micro-ATX',
            memory_type='DDR5', memory_slots=4, max_memory_gb=192,
            supported_cpu_families=['Ryzen 7000', 'Ryzen 8000G'],
        )
        ram_ddr4 = _make_part(
            'ram', 'Corsair Vengeance 16GB DDR4',
            memory_type='DDR4', ram_capacity_gb=16, ram_modules=2, ram_speed_mhz=3200,
        )
        report = self.engine.evaluate_products({'cpu': cpu, 'motherboard': mobo, 'ram': ram_ddr4})
        self.assertEqual(report.overall_status, STATUS_INCOMPATIBLE)
        codes = {c.rule_code for c in report.incompatibilities}
        self.assertIn('MOBO_RAM_DDR_MISMATCH', codes)
        self.assertIn('CPU_RAM_TYPE_MISMATCH', codes)

    def test_ram_slot_count_and_capacity_limits_and_xmp_warning(self):
        cpu = _make_part(
            'cpu', 'Core i5-12400',
            socket='LGA1700', cpu_family='Intel 12th Gen', tdp_watts=65,
            integrated_graphics=True, includes_stock_cooler=True,
            supported_memory_types=['DDR4', 'DDR5'], max_memory_gb=128, max_memory_speed_mhz=4800,
        )
        mobo_2slot = _make_part(
            'motherboard', 'Budget H610M 2-DIMM',
            socket='LGA1700', chipset='H610', form_factor='Micro-ATX',
            memory_type='DDR5', memory_slots=2, max_memory_gb=64,
            supported_cpu_families=['Intel 12th Gen'],
        )
        ram_2x32 = _make_part(
            'ram', 'G.Skill 64GB DDR5-6000',
            memory_type='DDR5', ram_capacity_gb=64, ram_modules=2, ram_speed_mhz=6000,
        )
        # qty=2 of 2x32GB -> 4 modules on 2-slot board -> incompatible
        report_too_many = self.engine.evaluate_products({'cpu': cpu, 'motherboard': mobo_2slot, 'ram': (ram_2x32, 2)})
        self.assertEqual(report_too_many.overall_status, STATUS_INCOMPATIBLE)
        self.assertTrue(any(c.rule_code == 'MOBO_RAM_SLOTS_EXCEEDED' for c in report_too_many.incompatibilities))

        # qty=1 fits 2 slots & 64GB cap, but 6000 MT/s exceeds 4800 MT/s official JEDEC -> XMP warning
        report_xmp = self.engine.evaluate_products({'cpu': cpu, 'motherboard': mobo_2slot, 'ram': (ram_2x32, 1)})
        self.assertEqual(report_xmp.overall_status, STATUS_WARNING)
        self.assertTrue(any(c.rule_code == 'CPU_RAM_XMP_WARNING' for c in report_xmp.warnings))

    def test_gpu_and_cooler_case_clearances_and_form_factor(self):
        gpu_long = _make_part('gpu', 'Triple Fan RTX 4080', gpu_length_mm=345, tdp_watts=320, recommended_psu_watts=750)
        case_compact = _make_part(
            'case', 'Compact mATX Mini',
            supported_form_factors=['Micro-ATX', 'Mini-ITX'],
            max_gpu_length_mm=310,
            max_cooler_height_mm=155,
            supported_radiator_sizes_mm=[120, 240],
        )
        cooler_tall_air = _make_part(
            'cooler', 'Tall Dual-Tower Air',
            cooler_type='Air', cooler_height_mm=165, supported_sockets=['AM5', 'LGA1700'],
        )
        cooler_aio_360 = _make_part(
            'cooler', 'Huge 360mm AIO',
            cooler_type='Liquid AIO', radiator_size_mm=360, supported_sockets=['AM5', 'LGA1700'],
        )
        mobo_atx = _make_part(
            'motherboard', 'Full ATX Z790',
            socket='LGA1700', chipset='Z790', form_factor='ATX', memory_type='DDR5',
        )

        r1 = self.engine.evaluate_products({'gpu': gpu_long, 'case': case_compact, 'motherboard': mobo_atx, 'cooler': cooler_tall_air})
        codes1 = {c.rule_code for c in r1.incompatibilities}
        self.assertIn('GPU_CASE_TOO_LONG', codes1)
        self.assertIn('COOLER_CASE_TOO_TALL', codes1)
        self.assertIn('MOBO_CASE_FORM_FACTOR_MISMATCH', codes1)

        r2 = self.engine.evaluate_products({'case': case_compact, 'cooler': cooler_aio_360})
        self.assertTrue(any(c.rule_code == 'COOLER_CASE_RAD_UNSUPPORTED' for c in r2.incompatibilities))

    def test_cpu_cooler_socket_and_missing_stock_cooler(self):
        cpu_k = _make_part(
            'cpu', 'Core i5-14600K',
            socket='LGA1700', cpu_family='Intel 14th Gen', tdp_watts=125, max_power_watts=181,
            integrated_graphics=True, includes_stock_cooler=False,
        )
        cooler_am4_only = _make_part(
            'cooler', 'Legacy AM4 Cooler',
            cooler_type='Air', cooler_height_mm=150, supported_sockets=['AM4'], max_tdp_rating_watts=150,
        )
        r_no_cooler = self.engine.evaluate_products({'cpu': cpu_k})
        self.assertTrue(any(c.rule_code == 'CPU_NEEDS_COOLER' for c in r_no_cooler.warnings))

        r_mismatch = self.engine.evaluate_products({'cpu': cpu_k, 'cooler': cooler_am4_only})
        self.assertTrue(any(c.rule_code == 'CPU_COOLER_SOCKET_MISMATCH' for c in r_mismatch.incompatibilities))

    def test_psu_wattage_and_12vhpwr_connector_checks(self):
        cpu = _make_part('cpu', 'i9 Test CPU', socket='LGA1700', tdp_watts=125, max_power_watts=253, includes_stock_cooler=True, integrated_graphics=True)
        gpu_12v = _make_part(
            'gpu', 'RTX 4070 Ti Super',
            gpu_length_mm=300, tdp_watts=285, recommended_psu_watts=700,
            required_power_connectors={'pcie_16pin_12vhpwr': 1},
        )
        psu_low = _make_part(
            'psu', 'Budget 450W',
            wattage=450, psu_length_mm=140,
            psu_connectors={'pcie_8pin': 1, 'pcie_16pin_12vhpwr': 0},
        )
        psu_adapter_ok = _make_part(
            'psu', '750W ATX 2.4',
            wattage=750, psu_length_mm=150,
            psu_connectors={'pcie_8pin': 3, 'pcie_16pin_12vhpwr': 0},
        )
        psu_atx3 = _make_part(
            'psu', '750W ATX 3.0',
            wattage=750, psu_length_mm=150,
            psu_connectors={'pcie_8pin': 3, 'pcie_16pin_12vhpwr': 1},
        )

        r_low = self.engine.evaluate_products({'cpu': cpu, 'gpu': gpu_12v, 'psu': psu_low})
        low_codes = {c.rule_code for c in r_low.incompatibilities}
        self.assertIn('PSU_WATTAGE_INSUFFICIENT', low_codes)
        self.assertIn('PSU_12VHPWR_CONNECTORS_MISSING', low_codes)

        r_adapt = self.engine.evaluate_products({'cpu': cpu, 'gpu': gpu_12v, 'psu': psu_adapter_ok})
        self.assertEqual(r_adapt.overall_status, STATUS_WARNING)
        self.assertTrue(any(c.rule_code == 'PSU_12VHPWR_ADAPTER_WARNING' for c in r_adapt.warnings))

        r_atx3 = self.engine.evaluate_products({'cpu': cpu, 'gpu': gpu_12v, 'psu': psu_atx3})
        self.assertTrue(r_atx3.is_build_valid_compatible)
        self.assertFalse(any(c.rule_code == 'PSU_12VHPWR_ADAPTER_WARNING' for c in r_atx3.warnings))

    def test_storage_m2_limits_and_slot_sharing_notes(self):
        mobo = _make_part(
            'motherboard', '1-M2 Board',
            socket='AM4', chipset='A520', form_factor='Micro-ATX', memory_type='DDR4',
            m2_slots=1, m2_nvme_slots=1, m2_sata_slots=1, sata_ports=4,
            slot_sharing_notes='SATA ports 3-4 disabled when secondary slot populated.',
        )
        nvme_1 = _make_part('storage', 'NVMe 1TB', storage_type='NVMe M.2', capacity_gb=1000)
        nvme_2 = _make_part('storage', 'NVMe 2TB', storage_type='NVMe M.2', capacity_gb=2000)
        sata_ssd = _make_part('storage', 'SATA 2.5 SSD', storage_type='SATA 2.5" SSD', storage_form_factor='2.5"', capacity_gb=1000)

        r_exceeded = self.engine.evaluate_products({'motherboard': mobo, 'storage': nvme_1, 'storage_secondary': nvme_2})
        self.assertEqual(r_exceeded.overall_status, STATUS_INCOMPATIBLE)
        self.assertTrue(any(c.rule_code == 'STORAGE_M2_EXCEEDED' for c in r_exceeded.incompatibilities))

        r_ok = self.engine.evaluate_products({'motherboard': mobo, 'storage': nvme_1, 'storage_secondary': sata_ssd})
        self.assertTrue(r_ok.is_build_valid_compatible)
        self.assertTrue(any(c.rule_code == 'STORAGE_SLOT_SHARING_WARNING' for c in r_ok.warnings))

    def test_missing_specifications_never_assumed_compatible(self):
        # Product without HardwareSpecProfile at all
        cpu_unverified = _make_part('cpu', 'Mystery Unverified CPU')
        mobo_unverified = _make_part('motherboard', 'Mystery Unverified Board')
        report = self.engine.evaluate_products({'cpu': cpu_unverified, 'motherboard': mobo_unverified})
        self.assertEqual(report.overall_status, STATUS_UNKNOWN)
        self.assertEqual(len(report.compatible_checks), 0)
        self.assertTrue(len(report.unknowns) > 0)

    def test_seeded_catalog_legacy_ryzen_1400_with_b550_is_incompatible(self):
        # Create a legacy-like row to verify seed_hardware_catalog enriches it and B550 rejects it
        Product.objects.create(
            name='AMD ryzen 5 1400',
            legacy_category='Processors',
            price=Decimal('9000.00'),
        )
        call_command('seed_hardware_catalog')
        ryzen_1400 = Product.objects.filter(name='AMD ryzen 5 1400', is_active=True).first()
        b550_mobo = Product.objects.filter(category__component_slot='motherboard', spec_profile__chipset='B550').first()
        b450_mobo = Product.objects.filter(category__component_slot='motherboard', spec_profile__chipset='B450').first()
        ryzen_5600 = Product.objects.filter(name__icontains='Ryzen 5 5600').first()
        self.assertIsNotNone(ryzen_1400)
        self.assertIsNotNone(b550_mobo)
        self.assertIsNotNone(b450_mobo)
        self.assertIsNotNone(ryzen_5600)

        report_b550 = self.engine.evaluate_products({'cpu': ryzen_1400, 'motherboard': b550_mobo})
        self.assertEqual(report_b550.overall_status, STATUS_INCOMPATIBLE)

        report_b450 = self.engine.evaluate_products({'cpu': ryzen_5600, 'motherboard': b450_mobo})
        self.assertEqual(report_b450.overall_status, STATUS_WARNING)
