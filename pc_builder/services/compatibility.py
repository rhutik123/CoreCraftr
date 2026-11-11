"""
Deterministic Rule-Based Hardware Compatibility Engine.

IMPORTANT: Compatibility decisions are ALWAYS computed here using structured
hardware specifications and explicit manufacturer/platform rules — NEVER by AI.
Missing specifications always result in 'unknown' (or 'warning' where partial
matches exist), never silent 'compatible'.
"""

from dataclasses import dataclass, field
from typing import Optional
from pc_builder.models import ChipsetCPUSupport, MotherboardCPUSupport


STATUS_COMPATIBLE = 'compatible'
STATUS_INCOMPATIBLE = 'incompatible'
STATUS_WARNING = 'warning'
STATUS_UNKNOWN = 'unknown'

STATUS_PRIORITY = {
    STATUS_COMPATIBLE: 0,
    STATUS_UNKNOWN: 1,
    STATUS_WARNING: 2,
    STATUS_INCOMPATIBLE: 3,
}


@dataclass
class CompatibilityIssue:
    rule_code: str
    category: str
    status: str  # compatible | warning | incompatible | unknown
    title: str
    message: str
    affected_slots: list[str] = field(default_factory=list)
    suggestion: str = ''

    def to_dict(self):
        return {
            'rule_code': self.rule_code,
            'category': self.category,
            'status': self.status,
            'title': self.title,
            'message': self.message,
            'affected_slots': self.affected_slots,
            'suggestion': self.suggestion,
        }


@dataclass
class CompatibilityReport:
    overall_status: str
    checks: list[CompatibilityIssue] = field(default_factory=list)
    estimated_wattage: int = 0
    recommended_psu_wattage: int = 0
    wattage_incomplete: bool = False

    @property
    def issues(self):
        return [c for c in self.checks if c.status != STATUS_COMPATIBLE]

    @property
    def incompatibilities(self):
        return [c for c in self.checks if c.status == STATUS_INCOMPATIBLE]

    @property
    def warnings(self):
        return [c for c in self.checks if c.status == STATUS_WARNING]

    @property
    def unknowns(self):
        return [c for c in self.checks if c.status == STATUS_UNKNOWN]

    @property
    def compatible_checks(self):
        return [c for c in self.checks if c.status == STATUS_COMPATIBLE]

    @property
    def is_build_valid_compatible(self):
        return len(self.incompatibilities) == 0

    def to_dict(self):
        return {
            'overall_status': self.overall_status,
            'estimated_wattage': self.estimated_wattage,
            'recommended_psu_wattage': self.recommended_psu_wattage,
            'wattage_incomplete': self.wattage_incomplete,
            'counts': {
                'compatible': len(self.compatible_checks),
                'warning': len(self.warnings),
                'incompatible': len(self.incompatibilities),
                'unknown': len(self.unknowns),
            },
            'checks': [c.to_dict() for c in self.checks],
            'issues': [c.to_dict() for c in self.issues],
        }


class CompatibilityEngine:
    """Evaluates a mapping of {slot: Product} or {slot: (Product, quantity)} deterministically."""

    BASE_SYSTEM_OVERHEAD_WATTS = 50
    STORAGE_DRIVE_WATTS = 10
    RAM_STICK_WATTS = 5
    FAN_PACK_WATTS = 10

    def evaluate_build(self, build) -> CompatibilityReport:
        slot_items = {}
        for comp in build.components.select_related(
            'product',
            'product__category',
            'product__brand',
            'product__spec_profile',
        ):
            slot_items[comp.slot] = (comp.product, comp.quantity)
        return self.evaluate_products(slot_items)

    def evaluate_products(self, slot_items: dict) -> CompatibilityReport:
        """
        slot_items: dict mapping slot name -> Product or (Product, quantity).
        """
        normalized: dict[str, tuple] = {}
        for slot, val in slot_items.items():
            if val is None:
                continue
            if isinstance(val, tuple):
                prod, qty = val
            else:
                prod, qty = val, 1
            if prod is not None:
                normalized[slot] = (prod, max(1, int(qty)))

        checks: list[CompatibilityIssue] = []

        cpu_entry = normalized.get('cpu')
        mobo_entry = normalized.get('motherboard')
        ram_entry = normalized.get('ram')
        gpu_entry = normalized.get('gpu')
        psu_entry = normalized.get('psu')
        case_entry = normalized.get('case')
        cooler_entry = normalized.get('cooler')
        fan_entry = normalized.get('case_fan')

        storage_entries = []
        if 'storage' in normalized:
            storage_entries.append(('storage', normalized['storage']))
        if 'storage_secondary' in normalized:
            storage_entries.append(('storage_secondary', normalized['storage_secondary']))

        # 1. CPU + Motherboard
        if cpu_entry and mobo_entry:
            checks.append(self._check_cpu_motherboard(cpu_entry[0], mobo_entry[0]))

        # 2. Motherboard + RAM
        if mobo_entry and ram_entry:
            checks.extend(self._check_motherboard_ram(mobo_entry[0], ram_entry[0], ram_entry[1]))

        # 3. CPU + RAM
        if cpu_entry and ram_entry:
            checks.extend(self._check_cpu_ram(cpu_entry[0], ram_entry[0], ram_entry[1]))

        # 4. GPU + Case
        if gpu_entry and case_entry:
            checks.append(self._check_gpu_case(gpu_entry[0], case_entry[0]))

        # 5. Cooler + Case
        if cooler_entry and case_entry:
            checks.append(self._check_cooler_case(cooler_entry[0], case_entry[0]))

        # 6. CPU + Cooler (and missing cooler check)
        if cpu_entry:
            checks.extend(
                self._check_cpu_cooler(
                    cpu_entry[0],
                    cooler_entry[0] if cooler_entry else None,
                )
            )

        # 7. Motherboard + Case
        if mobo_entry and case_entry:
            checks.append(self._check_motherboard_case(mobo_entry[0], case_entry[0]))

        # 8. Storage + Motherboard (+ Case bays)
        if storage_entries and mobo_entry:
            checks.extend(
                self._check_storage_motherboard(
                    storage_entries,
                    mobo_entry[0],
                    case_entry[0] if case_entry else None,
                )
            )
        elif storage_entries and case_entry:
            checks.extend(self._check_storage_case_bays(storage_entries, case_entry[0]))

        # 9. Estimated Power & PSU Checks
        est_watts, rec_psu_watts, wattage_incomplete = self._estimate_power(
            cpu_entry, gpu_entry, ram_entry, storage_entries, fan_entry
        )
        if psu_entry:
            checks.extend(
                self._check_psu(
                    psu_entry[0],
                    est_watts,
                    rec_psu_watts,
                    wattage_incomplete,
                    gpu_entry[0] if gpu_entry else None,
                    mobo_entry[0] if mobo_entry else None,
                    case_entry[0] if case_entry else None,
                )
            )

        # 10. Display output & single-channel advisory checks
        if cpu_entry and not gpu_entry:
            cpu_spec = self._spec(cpu_entry[0])
            if cpu_spec is None or cpu_spec.integrated_graphics is None:
                checks.append(CompatibilityIssue(
                    rule_code='DISPLAY_IGPU_UNKNOWN',
                    category='Display Output',
                    status=STATUS_UNKNOWN,
                    title='Integrated Graphics Status Unknown',
                    message=f'Unable to verify whether {cpu_entry[0].name} includes integrated graphics.',
                    affected_slots=['cpu', 'gpu'],
                    suggestion='Add a dedicated GPU or confirm the CPU has integrated graphics.',
                ))
            elif cpu_spec.integrated_graphics is False:
                checks.append(CompatibilityIssue(
                    rule_code='DISPLAY_NO_GPU',
                    category='Display Output',
                    status=STATUS_WARNING,
                    title='Dedicated GPU Required for Video Output',
                    message=(
                        f'{cpu_entry[0].name} does not have integrated graphics. '
                        'Your PC will not output video to a monitor without a dedicated GPU.'
                    ),
                    affected_slots=['cpu', 'gpu'],
                    suggestion='Select a dedicated graphics card in the GPU slot or switch to an APU/iGPU CPU.',
                ))

        if ram_entry:
            ram_spec = self._spec(ram_entry[0])
            if ram_spec and ram_spec.ram_modules and (ram_spec.ram_modules * ram_entry[1]) == 1:
                checks.append(CompatibilityIssue(
                    rule_code='RAM_SINGLE_CHANNEL',
                    category='Memory Configuration',
                    status=STATUS_WARNING,
                    title='Single-Channel Memory Configuration',
                    message=(
                        f'{ram_entry[0].name} is a single module. Running single-channel RAM '
                        'reduces memory bandwidth compared to a dual-channel (2-stick) kit.'
                    ),
                    affected_slots=['ram'],
                    suggestion='Consider a 2-stick (2x8GB or 2x16GB) kit or set RAM quantity to 2.',
                ))

        # Determine overall status
        if not checks:
            if len(normalized) <= 1:
                overall = STATUS_UNKNOWN if len(normalized) == 0 else STATUS_COMPATIBLE
                if len(normalized) == 1:
                    only_slot, (only_prod, _) = next(iter(normalized.items()))
                    if self._spec(only_prod) is None:
                        overall = STATUS_UNKNOWN
                        checks.append(CompatibilityIssue(
                            rule_code='SPEC_MISSING_SINGLE',
                            category='Specification Data',
                            status=STATUS_UNKNOWN,
                            title='Incomplete Component Specification',
                            message=f'Structured hardware specifications for {only_prod.name} are incomplete.',
                            affected_slots=[only_slot],
                        ))
            else:
                overall = STATUS_UNKNOWN
        else:
            max_prio = max(STATUS_PRIORITY[c.status] for c in checks)
            overall = next(k for k, v in STATUS_PRIORITY.items() if v == max_prio)

        return CompatibilityReport(
            overall_status=overall,
            checks=checks,
            estimated_wattage=est_watts,
            recommended_psu_wattage=rec_psu_watts,
            wattage_incomplete=wattage_incomplete,
        )

    @staticmethod
    def _spec(product):
        try:
            return product.spec_profile
        except Exception:
            return None

    def _check_cpu_motherboard(self, cpu, mobo) -> CompatibilityIssue:
        cpu_spec = self._spec(cpu)
        mobo_spec = self._spec(mobo)

        if not cpu_spec or not mobo_spec or not cpu_spec.socket or not mobo_spec.socket:
            return CompatibilityIssue(
                rule_code='CPU_MOBO_SPEC_UNKNOWN',
                category='CPU & Motherboard',
                status=STATUS_UNKNOWN,
                title='CPU / Motherboard Socket Unknown',
                message=(
                    f'Verified socket information is missing for {cpu.name} or {mobo.name}. '
                    'Missing data cannot be assumed compatible.'
                ),
                affected_slots=['cpu', 'motherboard'],
                suggestion='Verify socket and CPU support list on the manufacturer website.',
            )

        if cpu_spec.socket.strip().upper() != mobo_spec.socket.strip().upper():
            return CompatibilityIssue(
                rule_code='CPU_MOBO_SOCKET_MISMATCH',
                category='CPU & Motherboard',
                status=STATUS_INCOMPATIBLE,
                title='CPU & Motherboard Socket Mismatch',
                message=(
                    f'{cpu.name} uses socket {cpu_spec.socket}, which is physically and electrically '
                    f'incompatible with {mobo.name} (socket {mobo_spec.socket}).'
                ),
                affected_slots=['cpu', 'motherboard'],
                suggestion=f'Choose a motherboard with socket {cpu_spec.socket} or change your CPU.',
            )

        # Sockets match — now check explicit MotherboardCPUSupport override first
        override = MotherboardCPUSupport.objects.filter(motherboard=mobo, cpu=cpu).first()
        if override:
            if override.status == 'unsupported':
                return CompatibilityIssue(
                    rule_code='CPU_MOBO_QVL_UNSUPPORTED',
                    category='CPU & Motherboard',
                    status=STATUS_INCOMPATIBLE,
                    title='CPU Not Supported on Motherboard CPU Support List',
                    message=override.notes or f'{mobo.name} does not support {cpu.name} despite matching socket {cpu_spec.socket}.',
                    affected_slots=['cpu', 'motherboard'],
                    suggestion='Select a motherboard whose chipset and QVL support this CPU generation.',
                )
            if override.status == 'bios_required':
                bios_note = f' (minimum BIOS: {override.min_bios_version})' if override.min_bios_version else ''
                return CompatibilityIssue(
                    rule_code='CPU_MOBO_BIOS_REQUIRED',
                    category='CPU & Motherboard',
                    status=STATUS_WARNING,
                    title='Motherboard BIOS Update May Be Required',
                    message=(override.notes or f'{mobo.name} supports {cpu.name}{bios_note}, which may require a BIOS update prior to boot.'),
                    affected_slots=['cpu', 'motherboard'],
                    suggestion='Confirm BIOS version with retailer or use a board with BIOS Flashback.',
                )
            return CompatibilityIssue(
                rule_code='CPU_MOBO_QVL_VERIFIED',
                category='CPU & Motherboard',
                status=STATUS_COMPATIBLE,
                title='CPU & Motherboard Verified Compatible',
                message=override.notes or f'{cpu.name} is verified compatible with {mobo.name} ({cpu_spec.socket}).',
                affected_slots=['cpu', 'motherboard'],
            )

        # Next check ChipsetCPUSupport matrix
        if mobo_spec.chipset and cpu_spec.cpu_family:
            chipset_rule = ChipsetCPUSupport.objects.filter(
                socket__iexact=cpu_spec.socket.strip(),
                chipset__iexact=mobo_spec.chipset.strip(),
                cpu_family__iexact=cpu_spec.cpu_family.strip(),
            ).first()
            if chipset_rule:
                if chipset_rule.status == 'incompatible':
                    return CompatibilityIssue(
                        rule_code='CPU_MOBO_CHIPSET_INCOMPATIBLE',
                        category='CPU & Motherboard',
                        status=STATUS_INCOMPATIBLE,
                        title='Chipset Does Not Support This CPU Generation',
                        message=(
                            chipset_rule.notes
                            or f'{mobo.name} ({mobo_spec.chipset} chipset) does not support {cpu_spec.cpu_family} CPUs even though both use socket {cpu_spec.socket}.'
                        ),
                        affected_slots=['cpu', 'motherboard'],
                        suggestion='Select a motherboard with a chipset that officially supports this CPU family.',
                    )
                if chipset_rule.status == 'bios_update_required':
                    return CompatibilityIssue(
                        rule_code='CPU_MOBO_CHIPSET_BIOS_WARNING',
                        category='CPU & Motherboard',
                        status=STATUS_WARNING,
                        title='BIOS Update May Be Required for This Chipset',
                        message=(
                            chipset_rule.notes
                            or f'{mobo.name} ({mobo_spec.chipset}) supports {cpu_spec.cpu_family} CPUs with an updated BIOS.'
                        ),
                        affected_slots=['cpu', 'motherboard'],
                        suggestion='Check if the motherboard includes BIOS Flashback or ships with an updated BIOS.',
                    )
                return CompatibilityIssue(
                    rule_code='CPU_MOBO_CHIPSET_COMPATIBLE',
                    category='CPU & Motherboard',
                    status=STATUS_COMPATIBLE,
                    title='CPU & Motherboard Chipset Verified Compatible',
                    message=(
                        chipset_rule.notes
                        or f'{cpu.name} ({cpu_spec.cpu_family}) is officially supported on {mobo_spec.chipset} ({cpu_spec.socket}).'
                    ),
                    affected_slots=['cpu', 'motherboard'],
                )

        # Next check motherboard supported_cpu_families JSON list
        if cpu_spec.cpu_family and mobo_spec.supported_cpu_families:
            allowed_families = [f.strip().lower() for f in mobo_spec.supported_cpu_families]
            if cpu_spec.cpu_family.strip().lower() not in allowed_families:
                return CompatibilityIssue(
                    rule_code='CPU_MOBO_FAMILY_UNSUPPORTED',
                    category='CPU & Motherboard',
                    status=STATUS_INCOMPATIBLE,
                    title='CPU Family Not Listed in Motherboard Support',
                    message=(
                        f'{cpu.name} ({cpu_spec.cpu_family}) is not in {mobo.name}\'s supported CPU families '
                        f'({", ".join(mobo_spec.supported_cpu_families)}), despite sharing socket {cpu_spec.socket}.'
                    ),
                    affected_slots=['cpu', 'motherboard'],
                    suggestion='Choose a motherboard explicitly supporting this CPU generation.',
                )
            if mobo_spec.min_bios_note and 'bios' in mobo_spec.min_bios_note.lower():
                return CompatibilityIssue(
                    rule_code='CPU_MOBO_BIOS_NOTE',
                    category='CPU & Motherboard',
                    status=STATUS_WARNING,
                    title='Verify Motherboard BIOS Compatibility',
                    message=f'Socket and family match ({cpu_spec.socket}), note: {mobo_spec.min_bios_note}',
                    affected_slots=['cpu', 'motherboard'],
                )
            return CompatibilityIssue(
                rule_code='CPU_MOBO_FAMILY_COMPATIBLE',
                category='CPU & Motherboard',
                status=STATUS_COMPATIBLE,
                title='CPU & Motherboard Compatible',
                message=f'{cpu.name} matches {mobo.name} socket ({cpu_spec.socket}) and supported CPU generation ({cpu_spec.cpu_family}).',
                affected_slots=['cpu', 'motherboard'],
            )

        # Socket matches, but chipset/CPU family support could not be verified
        return CompatibilityIssue(
            rule_code='CPU_MOBO_CHIPSET_UNKNOWN',
            category='CPU & Motherboard',
            status=STATUS_UNKNOWN,
            title='Socket Matches, CPU Support List Unverified',
            message=(
                f'Both {cpu.name} and {mobo.name} use socket {cpu_spec.socket}, '
                'but verified chipset/BIOS CPU support data is incomplete. '
                'Matching sockets alone do not guarantee compatibility.'
            ),
            affected_slots=['cpu', 'motherboard'],
            suggestion='Check the motherboard manufacturer QVL before purchasing.',
        )

    def _check_motherboard_ram(self, mobo, ram, ram_qty: int) -> list[CompatibilityIssue]:
        issues = []
        mobo_spec = self._spec(mobo)
        ram_spec = self._spec(ram)

        if not mobo_spec or not ram_spec or not mobo_spec.memory_type or not ram_spec.memory_type:
            issues.append(CompatibilityIssue(
                rule_code='MOBO_RAM_TYPE_UNKNOWN',
                category='Motherboard & RAM',
                status=STATUS_UNKNOWN,
                title='Memory Generation Unknown',
                message=f'DDR generation data is incomplete for {mobo.name} or {ram.name}.',
                affected_slots=['motherboard', 'ram'],
            ))
            return issues

        if mobo_spec.memory_type.strip().upper() != ram_spec.memory_type.strip().upper():
            issues.append(CompatibilityIssue(
                rule_code='MOBO_RAM_DDR_MISMATCH',
                category='Motherboard & RAM',
                status=STATUS_INCOMPATIBLE,
                title='RAM Generation Mismatch (DDR4 vs DDR5)',
                message=(
                    f'{mobo.name} only supports {mobo_spec.memory_type} memory, '
                    f'but {ram.name} is {ram_spec.memory_type}. DDR4 and DDR5 slots are physically keyed differently.'
                ),
                affected_slots=['motherboard', 'ram'],
                suggestion=f'Select {mobo_spec.memory_type} memory or switch to a {ram_spec.memory_type} motherboard.',
            ))
            return issues

        # Check DIMM slots & capacity limits
        if ram_spec.ram_modules is None or mobo_spec.memory_slots is None:
            issues.append(CompatibilityIssue(
                rule_code='MOBO_RAM_SLOTS_UNKNOWN',
                category='Motherboard & RAM',
                status=STATUS_UNKNOWN,
                title='DIMM Slot Count Unknown',
                message=f'Memory generation ({mobo_spec.memory_type}) matches, but slot counts are unverified.',
                affected_slots=['motherboard', 'ram'],
            ))
        else:
            total_modules = ram_spec.ram_modules * ram_qty
            if total_modules > mobo_spec.memory_slots:
                issues.append(CompatibilityIssue(
                    rule_code='MOBO_RAM_SLOTS_EXCEEDED',
                    category='Motherboard & RAM',
                    status=STATUS_INCOMPATIBLE,
                    title='Too Many RAM Modules for Motherboard',
                    message=(
                        f'Selected RAM configuration uses {total_modules} module(s), '
                        f'exceeding {mobo.name}\'s {mobo_spec.memory_slots} DIMM slots.'
                    ),
                    affected_slots=['motherboard', 'ram'],
                    suggestion='Reduce RAM kit quantity or choose a motherboard with 4 DIMM slots.',
                ))
                return issues

        if ram_spec.ram_capacity_gb and mobo_spec.max_memory_gb:
            total_gb = ram_spec.ram_capacity_gb * ram_qty
            if total_gb > mobo_spec.max_memory_gb:
                issues.append(CompatibilityIssue(
                    rule_code='MOBO_RAM_CAPACITY_EXCEEDED',
                    category='Motherboard & RAM',
                    status=STATUS_INCOMPATIBLE,
                    title='RAM Capacity Exceeds Motherboard Maximum',
                    message=(
                        f'Total selected RAM ({total_gb} GB) exceeds {mobo.name}\'s '
                        f'maximum supported capacity ({mobo_spec.max_memory_gb} GB).'
                    ),
                    affected_slots=['motherboard', 'ram'],
                ))
                return issues

        if ram_spec.ram_speed_mhz and mobo_spec.max_memory_speed_mhz:
            if ram_spec.ram_speed_mhz > mobo_spec.max_memory_speed_mhz:
                issues.append(CompatibilityIssue(
                    rule_code='MOBO_RAM_SPEED_DOWNCLOCK',
                    category='Motherboard & RAM',
                    status=STATUS_WARNING,
                    title='RAM Speed Exceeds Listed Motherboard Max',
                    message=(
                        f'{ram.name} is rated at {ram_spec.ram_speed_mhz} MT/s, while {mobo.name} '
                        f'lists up to {mobo_spec.max_memory_speed_mhz} MT/s. It may downclock to a supported profile.'
                    ),
                    affected_slots=['motherboard', 'ram'],
                ))
                return issues

        if not issues:
            issues.append(CompatibilityIssue(
                rule_code='MOBO_RAM_COMPATIBLE',
                category='Motherboard & RAM',
                status=STATUS_COMPATIBLE,
                title='Motherboard & RAM Verified Compatible',
                message=f'{ram.name} ({ram_spec.memory_type}) fits {mobo.name} slots and capacity limits.',
                affected_slots=['motherboard', 'ram'],
            ))
        return issues

    def _check_cpu_ram(self, cpu, ram, ram_qty: int) -> list[CompatibilityIssue]:
        issues = []
        cpu_spec = self._spec(cpu)
        ram_spec = self._spec(ram)

        if not cpu_spec or not ram_spec or not cpu_spec.supported_memory_types or not ram_spec.memory_type:
            issues.append(CompatibilityIssue(
                rule_code='CPU_RAM_UNKNOWN',
                category='CPU & RAM',
                status=STATUS_UNKNOWN,
                title='CPU Memory Controller Spec Unknown',
                message=f'Supported memory types could not be verified between {cpu.name} and {ram.name}.',
                affected_slots=['cpu', 'ram'],
            ))
            return issues

        allowed_types = [t.strip().upper() for t in cpu_spec.supported_memory_types]
        if ram_spec.memory_type.strip().upper() not in allowed_types:
            issues.append(CompatibilityIssue(
                rule_code='CPU_RAM_TYPE_MISMATCH',
                category='CPU & RAM',
                status=STATUS_INCOMPATIBLE,
                title='CPU Does Not Support Selected RAM Type',
                message=(
                    f'{cpu.name} memory controller supports {", ".join(allowed_types)}, '
                    f'not {ram_spec.memory_type}.'
                ),
                affected_slots=['cpu', 'ram'],
            ))
            return issues

        if ram_spec.ram_capacity_gb and cpu_spec.max_memory_gb:
            total_gb = ram_spec.ram_capacity_gb * ram_qty
            if total_gb > cpu_spec.max_memory_gb:
                issues.append(CompatibilityIssue(
                    rule_code='CPU_RAM_CAPACITY_EXCEEDED',
                    category='CPU & RAM',
                    status=STATUS_INCOMPATIBLE,
                    title='RAM Exceeds CPU Maximum Capacity',
                    message=(
                        f'Total RAM ({total_gb} GB) exceeds {cpu.name}\'s maximum supported '
                        f'memory capacity ({cpu_spec.max_memory_gb} GB).'
                    ),
                    affected_slots=['cpu', 'ram'],
                ))
                return issues

        if ram_spec.ram_speed_mhz and cpu_spec.max_memory_speed_mhz:
            if ram_spec.ram_speed_mhz > cpu_spec.max_memory_speed_mhz:
                issues.append(CompatibilityIssue(
                    rule_code='CPU_RAM_XMP_WARNING',
                    category='CPU & RAM',
                    status=STATUS_WARNING,
                    title='RAM Requires XMP / EXPO Profile Above Official CPU Spec',
                    message=(
                        f'{ram.name} ({ram_spec.ram_speed_mhz} MT/s) exceeds {cpu.name}\'s official '
                        f'JEDEC spec ({cpu_spec.max_memory_speed_mhz} MT/s). Enable XMP/EXPO in BIOS to reach rated speed.'
                    ),
                    affected_slots=['cpu', 'ram'],
                ))
                return issues

        issues.append(CompatibilityIssue(
            rule_code='CPU_RAM_COMPATIBLE',
            category='CPU & RAM',
            status=STATUS_COMPATIBLE,
            title='CPU & RAM Verified Compatible',
            message=f'{cpu.name} officially supports {ram_spec.memory_type} within configured speed/capacity.',
            affected_slots=['cpu', 'ram'],
        ))
        return issues

    def _check_gpu_case(self, gpu, case) -> CompatibilityIssue:
        gpu_spec = self._spec(gpu)
        case_spec = self._spec(case)

        if not gpu_spec or not case_spec or gpu_spec.gpu_length_mm is None or case_spec.max_gpu_length_mm is None:
            return CompatibilityIssue(
                rule_code='GPU_CASE_UNKNOWN',
                category='GPU & Case Clearance',
                status=STATUS_UNKNOWN,
                title='GPU / Case Clearance Unknown',
                message=f'Length or clearance specs are incomplete for {gpu.name} or {case.name}.',
                affected_slots=['gpu', 'case'],
            )

        diff = case_spec.max_gpu_length_mm - gpu_spec.gpu_length_mm
        if diff < 0:
            return CompatibilityIssue(
                rule_code='GPU_CASE_TOO_LONG',
                category='GPU & Case Clearance',
                status=STATUS_INCOMPATIBLE,
                title='GPU Exceeds Case Length Clearance',
                message=(
                    f'{gpu.name} is {gpu_spec.gpu_length_mm} mm long, exceeding {case.name}\'s '
                    f'maximum GPU clearance of {case_spec.max_gpu_length_mm} mm.'
                ),
                affected_slots=['gpu', 'case'],
                suggestion='Choose a shorter dual-fan GPU or a larger mid-tower PC cabinet.',
            )

        if diff <= 10:
            return CompatibilityIssue(
                rule_code='GPU_CASE_TIGHT',
                category='GPU & Case Clearance',
                status=STATUS_WARNING,
                title='Tight GPU Clearance in Case',
                message=(
                    f'{gpu.name} ({gpu_spec.gpu_length_mm} mm) leaves only {diff} mm inside {case.name} '
                    f'(max {case_spec.max_gpu_length_mm} mm). Front-mounted AIO radiators may interfere.'
                ),
                affected_slots=['gpu', 'case'],
            )

        return CompatibilityIssue(
            rule_code='GPU_CASE_COMPATIBLE',
            category='GPU & Case Clearance',
            status=STATUS_COMPATIBLE,
            title='GPU Fits Case Clearance',
            message=f'{gpu.name} ({gpu_spec.gpu_length_mm} mm) fits comfortably inside {case.name} (max {case_spec.max_gpu_length_mm} mm).',
            affected_slots=['gpu', 'case'],
        )

    def _check_cooler_case(self, cooler, case) -> CompatibilityIssue:
        cooler_spec = self._spec(cooler)
        case_spec = self._spec(case)

        if not cooler_spec or not case_spec or not cooler_spec.cooler_type:
            return CompatibilityIssue(
                rule_code='COOLER_CASE_UNKNOWN',
                category='Cooler & Case Clearance',
                status=STATUS_UNKNOWN,
                title='Cooler / Case Clearance Unknown',
                message=f'Cooler dimensions or case clearance could not be verified for {cooler.name} and {case.name}.',
                affected_slots=['cooler', 'case'],
            )

        ctype = cooler_spec.cooler_type.strip().lower()
        if 'air' in ctype:
            if cooler_spec.cooler_height_mm is None or case_spec.max_cooler_height_mm is None:
                return CompatibilityIssue(
                    rule_code='COOLER_CASE_HEIGHT_UNKNOWN',
                    category='Cooler & Case Clearance',
                    status=STATUS_UNKNOWN,
                    title='Air Cooler Height Clearance Unknown',
                    message='Missing cooler height or case maximum cooler clearance.',
                    affected_slots=['cooler', 'case'],
                )
            diff = case_spec.max_cooler_height_mm - cooler_spec.cooler_height_mm
            if diff < 0:
                return CompatibilityIssue(
                    rule_code='COOLER_CASE_TOO_TALL',
                    category='Cooler & Case Clearance',
                    status=STATUS_INCOMPATIBLE,
                    title='CPU Cooler Too Tall for Case',
                    message=(
                        f'{cooler.name} height is {cooler_spec.cooler_height_mm} mm, exceeding {case.name}\'s '
                        f'maximum cooler height of {case_spec.max_cooler_height_mm} mm.'
                    ),
                    affected_slots=['cooler', 'case'],
                    suggestion='Select a lower-profile air cooler, a 240mm AIO, or a wider case.',
                )
            if diff <= 4:
                return CompatibilityIssue(
                    rule_code='COOLER_CASE_TIGHT',
                    category='Cooler & Case Clearance',
                    status=STATUS_WARNING,
                    title='Tight CPU Cooler Side-Panel Clearance',
                    message=(
                        f'{cooler.name} ({cooler_spec.cooler_height_mm} mm) clears {case.name} '
                        f'({case_spec.max_cooler_height_mm} mm) by only {diff} mm.'
                    ),
                    affected_slots=['cooler', 'case'],
                )
            return CompatibilityIssue(
                rule_code='COOLER_CASE_COMPATIBLE',
                category='Cooler & Case Clearance',
                status=STATUS_COMPATIBLE,
                title='CPU Cooler Fits Case Clearance',
                message=f'{cooler.name} ({cooler_spec.cooler_height_mm} mm) fits {case.name} (max {case_spec.max_cooler_height_mm} mm).',
                affected_slots=['cooler', 'case'],
            )

        if 'liquid' in ctype or 'aio' in ctype:
            if cooler_spec.radiator_size_mm is None or not case_spec.supported_radiator_sizes_mm:
                return CompatibilityIssue(
                    rule_code='COOLER_CASE_RAD_UNKNOWN',
                    category='Cooler & Case Clearance',
                    status=STATUS_UNKNOWN,
                    title='Radiator Mounting Support Unknown',
                    message='Missing radiator size or case radiator mounting list.',
                    affected_slots=['cooler', 'case'],
                )
            if cooler_spec.radiator_size_mm not in case_spec.supported_radiator_sizes_mm:
                return CompatibilityIssue(
                    rule_code='COOLER_CASE_RAD_UNSUPPORTED',
                    category='Cooler & Case Clearance',
                    status=STATUS_INCOMPATIBLE,
                    title='Radiator Size Not Supported by Case',
                    message=(
                        f'{cooler.name} requires a {cooler_spec.radiator_size_mm} mm radiator mount, '
                        f'but {case.name} supports {case_spec.supported_radiator_sizes_mm} mm.'
                    ),
                    affected_slots=['cooler', 'case'],
                    suggestion='Choose a 240mm AIO or a case supporting 360mm radiators.',
                )
            return CompatibilityIssue(
                rule_code='COOLER_CASE_RAD_COMPATIBLE',
                category='Cooler & Case Clearance',
                status=STATUS_COMPATIBLE,
                title='Liquid Cooler Radiator Supported by Case',
                message=f'{cooler_spec.radiator_size_mm} mm radiator fits {case.name}.',
                affected_slots=['cooler', 'case'],
            )

        return CompatibilityIssue(
            rule_code='COOLER_TYPE_UNKNOWN',
            category='Cooler & Case Clearance',
            status=STATUS_UNKNOWN,
            title='Cooler Type Unrecognized',
            message=f'Could not classify cooler type for {cooler.name}.',
            affected_slots=['cooler', 'case'],
        )

    def _check_cpu_cooler(self, cpu, cooler) -> list[CompatibilityIssue]:
        issues = []
        cpu_spec = self._spec(cpu)

        if cooler is None:
            if not cpu_spec or cpu_spec.includes_stock_cooler is None:
                issues.append(CompatibilityIssue(
                    rule_code='CPU_STOCK_COOLER_UNKNOWN',
                    category='CPU Cooling',
                    status=STATUS_UNKNOWN,
                    title='Stock Cooler Status Unknown',
                    message=f'Unable to confirm whether {cpu.name} includes a cooler in the box.',
                    affected_slots=['cpu', 'cooler'],
                    suggestion='Select a compatible CPU cooler to be safe.',
                ))
            elif cpu_spec.includes_stock_cooler is False:
                issues.append(CompatibilityIssue(
                    rule_code='CPU_NEEDS_COOLER',
                    category='CPU Cooling',
                    status=STATUS_WARNING,
                    title='CPU Does Not Include a Stock Cooler',
                    message=f'{cpu.name} ships without a stock cooler in the box. A separate CPU cooler is required.',
                    affected_slots=['cpu', 'cooler'],
                    suggestion='Add a compatible tower air cooler or liquid AIO cooler.',
                ))
            return issues

        cooler_spec = self._spec(cooler)
        if not cpu_spec or not cooler_spec or not cpu_spec.socket or not cooler_spec.supported_sockets:
            issues.append(CompatibilityIssue(
                rule_code='CPU_COOLER_SOCKET_UNKNOWN',
                category='CPU & Cooler',
                status=STATUS_UNKNOWN,
                title='Cooler Socket Support Unknown',
                message=f'Socket mounting compatibility between {cpu.name} and {cooler.name} is unverified.',
                affected_slots=['cpu', 'cooler'],
            ))
            return issues

        supported = [s.strip().upper() for s in cooler_spec.supported_sockets]
        if cpu_spec.socket.strip().upper() not in supported:
            issues.append(CompatibilityIssue(
                rule_code='CPU_COOLER_SOCKET_MISMATCH',
                category='CPU & Cooler',
                status=STATUS_INCOMPATIBLE,
                title='Cooler Does Not Support CPU Socket',
                message=(
                    f'{cooler.name} supports sockets {", ".join(cooler_spec.supported_sockets)}, '
                    f'not {cpu.name}\'s socket {cpu_spec.socket}.'
                ),
                affected_slots=['cpu', 'cooler'],
                suggestion=f'Choose a cooler with {cpu_spec.socket} mounting hardware.',
            ))
            return issues

        cpu_thermal = cpu_spec.max_power_watts or cpu_spec.tdp_watts
        if cpu_thermal and cooler_spec.max_tdp_rating_watts:
            if cpu_thermal > cooler_spec.max_tdp_rating_watts:
                issues.append(CompatibilityIssue(
                    rule_code='CPU_COOLER_THERMAL_WARNING',
                    category='CPU & Cooler',
                    status=STATUS_WARNING,
                    title='Cooler Thermal Capacity May Be Tight',
                    message=(
                        f'{cpu.name} can draw up to {cpu_thermal}W under full boost, '
                        f'above {cooler.name}\'s {cooler_spec.max_tdp_rating_watts}W rating.'
                    ),
                    affected_slots=['cpu', 'cooler'],
                ))
                return issues

        issues.append(CompatibilityIssue(
            rule_code='CPU_COOLER_COMPATIBLE',
            category='CPU & Cooler',
            status=STATUS_COMPATIBLE,
            title='CPU & Cooler Verified Compatible',
            message=f'{cooler.name} supports {cpu_spec.socket} mounting and provides adequate thermal capacity.',
            affected_slots=['cpu', 'cooler'],
        ))
        return issues

    def _check_motherboard_case(self, mobo, case) -> CompatibilityIssue:
        mobo_spec = self._spec(mobo)
        case_spec = self._spec(case)

        if not mobo_spec or not case_spec or not mobo_spec.form_factor or not case_spec.supported_form_factors:
            return CompatibilityIssue(
                rule_code='MOBO_CASE_UNKNOWN',
                category='Motherboard & Case',
                status=STATUS_UNKNOWN,
                title='Motherboard / Case Form Factor Unknown',
                message=f'Form factor data is incomplete for {mobo.name} or {case.name}.',
                affected_slots=['motherboard', 'case'],
            )

        supported = [f.strip().lower() for f in case_spec.supported_form_factors]
        if mobo_spec.form_factor.strip().lower() not in supported:
            return CompatibilityIssue(
                rule_code='MOBO_CASE_FORM_FACTOR_MISMATCH',
                category='Motherboard & Case',
                status=STATUS_INCOMPATIBLE,
                title='Motherboard Form Factor Too Large for Case',
                message=(
                    f'{mobo.name} is {mobo_spec.form_factor}, which does not fit inside '
                    f'{case.name} (supports: {", ".join(case_spec.supported_form_factors)}).'
                ),
                affected_slots=['motherboard', 'case'],
                suggestion='Choose a Micro-ATX/Mini-ITX motherboard or an ATX mid-tower cabinet.',
            )

        return CompatibilityIssue(
            rule_code='MOBO_CASE_COMPATIBLE',
            category='Motherboard & Case',
            status=STATUS_COMPATIBLE,
            title='Motherboard Fits Case Form Factor',
            message=f'{mobo_spec.form_factor} form factor fits {case.name}.',
            affected_slots=['motherboard', 'case'],
        )

    def _check_storage_motherboard(self, storage_entries, mobo, case=None) -> list[CompatibilityIssue]:
        issues = []
        mobo_spec = self._spec(mobo)
        if not mobo_spec:
            issues.append(CompatibilityIssue(
                rule_code='STORAGE_MOBO_UNKNOWN',
                category='Storage & Motherboard',
                status=STATUS_UNKNOWN,
                title='Motherboard Storage Interfaces Unknown',
                message=f'M.2 and SATA slot counts are not verified for {mobo.name}.',
                affected_slots=['motherboard', 'storage'],
            ))
            return issues

        nvme_count = 0
        m2_sata_count = 0
        sata_count = 0
        unknown_storage = False
        affected = ['motherboard']

        for slot_name, (drive, qty) in storage_entries:
            affected.append(slot_name)
            d_spec = self._spec(drive)
            if not d_spec or not d_spec.storage_type:
                unknown_storage = True
                continue
            stype = d_spec.storage_type.lower()
            if 'nvme' in stype:
                nvme_count += qty
            elif 'm.2' in stype and 'sata' in stype:
                m2_sata_count += qty
            elif 'sata' in stype:
                sata_count += qty
            else:
                unknown_storage = True

        if unknown_storage:
            issues.append(CompatibilityIssue(
                rule_code='STORAGE_SPEC_UNKNOWN',
                category='Storage & Motherboard',
                status=STATUS_UNKNOWN,
                title='Storage Interface Specification Unknown',
                message='One or more storage drives lack verified interface/form-factor specs.',
                affected_slots=affected,
            ))

        total_m2 = nvme_count + m2_sata_count
        if total_m2 > 0:
            if mobo_spec.m2_slots is None or (nvme_count > 0 and mobo_spec.m2_nvme_slots is None):
                issues.append(CompatibilityIssue(
                    rule_code='STORAGE_M2_SLOTS_UNKNOWN',
                    category='Storage & Motherboard',
                    status=STATUS_UNKNOWN,
                    title='Motherboard M.2 Slot Count Unknown',
                    message=f'Cannot verify M.2 NVMe slot availability on {mobo.name}.',
                    affected_slots=affected,
                ))
            elif total_m2 > mobo_spec.m2_slots or (mobo_spec.m2_nvme_slots is not None and nvme_count > mobo_spec.m2_nvme_slots):
                issues.append(CompatibilityIssue(
                    rule_code='STORAGE_M2_EXCEEDED',
                    category='Storage & Motherboard',
                    status=STATUS_INCOMPATIBLE,
                    title='Insufficient Motherboard M.2 Slots',
                    message=(
                        f'Selected build uses {total_m2} M.2 drive(s) ({nvme_count} NVMe), '
                        f'exceeding {mobo.name}\'s {mobo_spec.m2_slots} M.2 slot(s).'
                    ),
                    affected_slots=affected,
                    suggestion='Switch secondary storage to a 2.5"/3.5" SATA drive or pick a motherboard with more M.2 slots.',
                ))
            elif m2_sata_count > 0 and mobo_spec.m2_sata_slots == 0:
                issues.append(CompatibilityIssue(
                    rule_code='STORAGE_M2_SATA_UNSUPPORTED',
                    category='Storage & Motherboard',
                    status=STATUS_INCOMPATIBLE,
                    title='M.2 SATA Drive Not Supported on NVMe-Only Slots',
                    message=f'{mobo.name} M.2 slots support PCIe NVMe only, not M.2 SATA drives.',
                    affected_slots=affected,
                ))

        if sata_count > 0:
            if mobo_spec.sata_ports is None:
                issues.append(CompatibilityIssue(
                    rule_code='STORAGE_SATA_UNKNOWN',
                    category='Storage & Motherboard',
                    status=STATUS_UNKNOWN,
                    title='Motherboard SATA Port Count Unknown',
                    message=f'Cannot verify SATA port count on {mobo.name}.',
                    affected_slots=affected,
                ))
            elif sata_count > mobo_spec.sata_ports:
                issues.append(CompatibilityIssue(
                    rule_code='STORAGE_SATA_EXCEEDED',
                    category='Storage & Motherboard',
                    status=STATUS_INCOMPATIBLE,
                    title='Insufficient Motherboard SATA Ports',
                    message=f'Selected SATA drives ({sata_count}) exceed {mobo.name}\'s {mobo_spec.sata_ports} SATA ports.',
                    affected_slots=affected,
                ))

        if mobo_spec.slot_sharing_notes and total_m2 > 0 and (sata_count > 0 or total_m2 > 1):
            issues.append(CompatibilityIssue(
                rule_code='STORAGE_SLOT_SHARING_WARNING',
                category='Storage & Motherboard',
                status=STATUS_WARNING,
                title='Potential M.2 / SATA Bandwidth Sharing',
                message=f'{mobo.name} slot-sharing note: {mobo_spec.slot_sharing_notes}',
                affected_slots=affected,
            ))

        if case:
            issues.extend(self._check_storage_case_bays(storage_entries, case))

        if not issues:
            issues.append(CompatibilityIssue(
                rule_code='STORAGE_MOBO_COMPATIBLE',
                category='Storage & Motherboard',
                status=STATUS_COMPATIBLE,
                title='Storage Drives Compatible with Motherboard',
                message=f'Selected storage drive(s) fit {mobo.name} M.2/SATA interfaces cleanly.',
                affected_slots=affected,
            ))
        return issues

    def _check_storage_case_bays(self, storage_entries, case) -> list[CompatibilityIssue]:
        issues = []
        case_spec = self._spec(case)
        count_35 = 0
        count_25 = 0
        for _, (drive, qty) in storage_entries:
            d_spec = self._spec(drive)
            if not d_spec:
                continue
            ff = (d_spec.storage_form_factor or '').lower()
            if '3.5' in ff:
                count_35 += qty
            elif '2.5' in ff:
                count_25 += qty

        if count_35 > 0:
            if not case_spec or case_spec.drive_bays_35 is None:
                issues.append(CompatibilityIssue(
                    rule_code='CASE_35_BAY_UNKNOWN',
                    category='Storage & Case',
                    status=STATUS_UNKNOWN,
                    title='3.5" Drive Bay Count Unknown',
                    message=f'Cannot confirm 3.5" HDD bay availability in {case.name}.',
                    affected_slots=['storage', 'case'],
                ))
            elif count_35 > case_spec.drive_bays_35:
                issues.append(CompatibilityIssue(
                    rule_code='CASE_35_BAY_EXCEEDED',
                    category='Storage & Case',
                    status=STATUS_INCOMPATIBLE,
                    title='Insufficient 3.5" Drive Bays in Case',
                    message=f'Selected 3.5" HDDs ({count_35}) exceed {case.name}\'s {case_spec.drive_bays_35} bay(s).',
                    affected_slots=['storage', 'case'],
                ))

        if count_25 > 0:
            if not case_spec or case_spec.drive_bays_25 is None:
                issues.append(CompatibilityIssue(
                    rule_code='CASE_25_BAY_UNKNOWN',
                    category='Storage & Case',
                    status=STATUS_UNKNOWN,
                    title='2.5" Drive Bay Count Unknown',
                    message=f'Cannot confirm 2.5" SSD bay availability in {case.name}.',
                    affected_slots=['storage', 'case'],
                ))
            elif count_25 > case_spec.drive_bays_25:
                issues.append(CompatibilityIssue(
                    rule_code='CASE_25_BAY_EXCEEDED',
                    category='Storage & Case',
                    status=STATUS_INCOMPATIBLE,
                    title='Insufficient 2.5" Drive Bays in Case',
                    message=f'Selected 2.5" SSDs ({count_25}) exceed {case.name}\'s {case_spec.drive_bays_25} bay(s).',
                    affected_slots=['storage', 'case'],
                ))
        return issues

    def _estimate_power(self, cpu_entry, gpu_entry, ram_entry, storage_entries, fan_entry) -> tuple[int, int, bool]:
        total = self.BASE_SYSTEM_OVERHEAD_WATTS
        incomplete = False

        if cpu_entry:
            cspec = self._spec(cpu_entry[0])
            cpu_w = (cspec.max_power_watts or cspec.tdp_watts) if cspec else None
            if cpu_w is None:
                incomplete = True
                total += 95
            else:
                total += cpu_w

        gpu_rec = 0
        if gpu_entry:
            gspec = self._spec(gpu_entry[0])
            if not gspec or gspec.tdp_watts is None:
                incomplete = True
                total += 200
            else:
                total += gspec.tdp_watts
            if gspec and gspec.recommended_psu_watts:
                gpu_rec = gspec.recommended_psu_watts

        if ram_entry:
            rspec = self._spec(ram_entry[0])
            sticks = (rspec.ram_modules if rspec and rspec.ram_modules else 2) * ram_entry[1]
            total += sticks * self.RAM_STICK_WATTS

        for _, (_, qty) in storage_entries:
            total += qty * self.STORAGE_DRIVE_WATTS

        if fan_entry:
            total += fan_entry[1] * self.FAN_PACK_WATTS

        # Recommended PSU: round up to nearest 50W with 25% headroom, or GPU manufacturer recommendation
        margin_watts = int(((total * 1.25) + 49) // 50 * 50)
        recommended = max(450 if gpu_entry else 350, margin_watts, gpu_rec)
        return total, recommended, incomplete

    def _check_psu(self, psu, est_watts: int, rec_watts: int, wattage_incomplete: bool, gpu=None, mobo=None, case=None) -> list[CompatibilityIssue]:
        issues = []
        psu_spec = self._spec(psu)

        if not psu_spec or psu_spec.wattage is None:
            issues.append(CompatibilityIssue(
                rule_code='PSU_WATTAGE_UNKNOWN',
                category='Power Supply',
                status=STATUS_UNKNOWN,
                title='PSU Wattage Unknown',
                message=f'Verified wattage rating is missing for {psu.name}.',
                affected_slots=['psu'],
            ))
            return issues

        if wattage_incomplete:
            issues.append(CompatibilityIssue(
                rule_code='PSU_ESTIMATE_INCOMPLETE',
                category='Power Supply',
                status=STATUS_WARNING,
                title='Estimated Power Draw Uses Partial Assumptions',
                message='One or more components are missing exact TDP/power specs; verify PSU headroom carefully.',
                affected_slots=['psu'],
            ))

        if psu_spec.wattage < est_watts:
            issues.append(CompatibilityIssue(
                rule_code='PSU_WATTAGE_INSUFFICIENT',
                category='Power Supply',
                status=STATUS_INCOMPATIBLE,
                title='PSU Wattage Too Low for System Load',
                message=(
                    f'{psu.name} provides {psu_spec.wattage}W, which is below the estimated '
                    f'peak system power draw of {est_watts}W (recommended: {rec_watts}W+).'
                ),
                affected_slots=['psu', 'gpu', 'cpu'],
                suggestion=f'Upgrade to at least a {rec_watts}W quality power supply.',
            ))
        elif psu_spec.wattage < rec_watts:
            issues.append(CompatibilityIssue(
                rule_code='PSU_HEADROOM_WARNING',
                category='Power Supply',
                status=STATUS_WARNING,
                title='Low PSU Power Headroom',
                message=(
                    f'{psu.name} ({psu_spec.wattage}W) covers estimated draw ({est_watts}W) '
                    f'but is below the recommended {rec_watts}W for transient spikes and efficiency.'
                ),
                affected_slots=['psu', 'gpu'],
                suggestion=f'Consider a {rec_watts}W+ unit for better headroom and longevity.',
            ))
        else:
            issues.append(CompatibilityIssue(
                rule_code='PSU_WATTAGE_COMPATIBLE',
                category='Power Supply',
                status=STATUS_COMPATIBLE,
                title='PSU Wattage Adequate',
                message=f'{psu.name} ({psu_spec.wattage}W) provides solid headroom for estimated {est_watts}W load (rec. {rec_watts}W).',
                affected_slots=['psu'],
            ))

        # Power connector checks for GPU
        if gpu:
            gpu_spec = self._spec(gpu)
            req = gpu_spec.required_power_connectors if gpu_spec else {}
            avail = psu_spec.psu_connectors or {}
            if not req or not avail:
                issues.append(CompatibilityIssue(
                    rule_code='PSU_GPU_CONNECTORS_UNKNOWN',
                    category='PSU Power Connectors',
                    status=STATUS_UNKNOWN,
                    title='GPU / PSU Connector Match Unverified',
                    message=f'Exact PCIe power cable counts are incomplete for {gpu.name} or {psu.name}.',
                    affected_slots=['psu', 'gpu'],
                ))
            else:
                req_16 = int(req.get('pcie_16pin_12vhpwr', 0) or 0)
                req_8 = int(req.get('pcie_8pin', 0) or 0)
                avail_16 = int(avail.get('pcie_16pin_12vhpwr', 0) or 0)
                avail_8 = int(avail.get('pcie_8pin', 0) or 0)

                if req_16 > avail_16:
                    # Check if PSU has enough 8-pin PCIe cables for a 2x8-pin to 16-pin adapter
                    needed_8_for_adapter = req_16 * 2
                    if avail_8 >= needed_8_for_adapter + req_8:
                        issues.append(CompatibilityIssue(
                            rule_code='PSU_12VHPWR_ADAPTER_WARNING',
                            category='PSU Power Connectors',
                            status=STATUS_WARNING,
                            title='12VHPWR Adapter Cable Required',
                            message=(
                                f'{gpu.name} uses a 16-pin 12VHPWR power header, which {psu.name} lacks natively. '
                                'You will need to use the GPU\'s bundled 8-pin-to-12VHPWR adapter.'
                            ),
                            affected_slots=['psu', 'gpu'],
                            suggestion='For cleaner cabling, consider an ATX 3.0 PSU with a native 12VHPWR cable.',
                        ))
                    else:
                        issues.append(CompatibilityIssue(
                            rule_code='PSU_12VHPWR_CONNECTORS_MISSING',
                            category='PSU Power Connectors',
                            status=STATUS_INCOMPATIBLE,
                            title='Insufficient PSU Power Connectors for GPU',
                            message=(
                                f'{gpu.name} requires a 16-pin 12VHPWR header (or 2+ dedicated 8-pin PCIe cables), '
                                f'which {psu.name} does not supply.'
                            ),
                            affected_slots=['psu', 'gpu'],
                        ))
                elif req_8 > avail_8:
                    issues.append(CompatibilityIssue(
                        rule_code='PSU_PCIE_8PIN_INSUFFICIENT',
                        category='PSU Power Connectors',
                        status=STATUS_INCOMPATIBLE,
                        title='Insufficient 8-Pin PCIe Power Cables',
                        message=f'{gpu.name} requires {req_8}x 8-pin PCIe connector(s), but {psu.name} provides {avail_8}.',
                        affected_slots=['psu', 'gpu'],
                    ))

        # PSU length vs Case
        if case:
            case_spec = self._spec(case)
            if psu_spec.psu_length_mm and case_spec and case_spec.max_psu_length_mm:
                if psu_spec.psu_length_mm > case_spec.max_psu_length_mm:
                    issues.append(CompatibilityIssue(
                        rule_code='PSU_CASE_TOO_LONG',
                        category='PSU & Case',
                        status=STATUS_INCOMPATIBLE,
                        title='PSU Length Exceeds Case Shroud Clearance',
                        message=(
                            f'{psu.name} length ({psu_spec.psu_length_mm} mm) exceeds {case.name}\'s '
                            f'maximum PSU clearance ({case_spec.max_psu_length_mm} mm).'
                        ),
                        affected_slots=['psu', 'case'],
                    ))

        return issues
