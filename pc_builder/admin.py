from django.contrib import admin
from .models import BuildComponent, ChipsetCPUSupport, MotherboardCPUSupport, PCBuild


@admin.register(ChipsetCPUSupport)
class ChipsetCPUSupportAdmin(admin.ModelAdmin):
    list_display = ('socket', 'chipset', 'cpu_family', 'status', 'source_reference')
    list_filter = ('socket', 'chipset', 'status')
    search_fields = ('socket', 'chipset', 'cpu_family', 'notes')


@admin.register(MotherboardCPUSupport)
class MotherboardCPUSupportAdmin(admin.ModelAdmin):
    list_display = ('motherboard', 'cpu', 'status', 'min_bios_version', 'source_reference')
    list_filter = ('status',)
    search_fields = ('motherboard__name', 'cpu__name', 'notes')


class BuildComponentInline(admin.TabularInline):
    model = BuildComponent
    extra = 0


@admin.register(PCBuild)
class PCBuildAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'mode', 'primary_use', 'budget', 'is_saved', 'is_active_workspace', 'updated_at')
    list_filter = ('mode', 'primary_use', 'is_saved', 'is_active_workspace')
    search_fields = ('name', 'user__username', 'uuid')
    inlines = [BuildComponentInline]
