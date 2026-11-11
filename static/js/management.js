(function () {
    'use strict';

    function getCsrfToken() {
        const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input && input.value) return input.value;
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    function refreshIcons() {
        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }
    }

    const productForm = document.getElementById('portal-product-form');
    if (!productForm) return;

    const schemaBaseUrl = productForm.dataset.schemaUrlTemplate;
    const duplicateCheckUrl = productForm.dataset.duplicateUrl;
    const aiResearchUrl = productForm.dataset.aiResearchUrl;
    const aiDiscardUrlTemplate = productForm.dataset.aiDiscardUrlTemplate;
    const productId = productForm.dataset.productId || '';

    const categorySelect = document.getElementById('id_category');
    const brandSelect = document.getElementById('id_brand');
    const newBrandInput = document.getElementById('id_new_brand_name');
    const nameInput = document.getElementById('id_name');
    const skuInput = document.getElementById('id_sku');
    const modelInput = document.getElementById('id_model_number');
    const priceInput = document.getElementById('id_price');
    const statusSelect = document.getElementById('id_status');
    const shortDescInput = document.getElementById('id_short_description');
    const galleryFileInput = document.getElementById('id_gallery_images');

    const dynamicSpecsContainer = document.getElementById('dynamic-spec-fields');
    const duplicateBox = document.getElementById('duplicate-warning-box');
    const customSpecContainer = document.getElementById('custom-spec-rows');
    const addCustomSpecBtn = document.getElementById('btn-add-custom-spec');

    function readCurrentSpecValues() {
        const vals = {};
        if (!dynamicSpecsContainer) return vals;
        dynamicSpecsContainer.querySelectorAll('[name^="spec_"]').forEach((el) => {
            vals[el.name.slice(5)] = el.value;
        });
        return vals;
    }

    function renderSpecFieldControl(field, currentVal) {
        const id = 'spec_input_' + field.name;
        const val = currentVal != null ? String(currentVal) : '';
        const criticalBadge = field.compatibility_critical
            ? '<span class="cc-badge cc-badge-warning text-[10px] ml-1.5 spec-critical-badge">Compatibility</span>'
            : '';
        const unitSuffix = field.unit
            ? '<span class="px-2.5 py-1.5 text-xs font-semibold text-muted bg-surface border border-l-0 border-border rounded-r-lg shrink-0">' + escapeHtml(field.unit) + '</span>'
            : '';

        let controlHtml = '';
        if (field.type === 'bool') {
            controlHtml =
                '<select class="cc-select cc-input-sm spec-live-input" id="' + id + '" name="spec_' + escapeHtml(field.name) + '" data-label="' + escapeHtml(field.label) + '" data-unit="">' +
                '<option value=""' + (val === '' ? ' selected' : '') + '>Unknown / Unspecified</option>' +
                '<option value="true"' + (val === 'true' ? ' selected' : '') + '>Yes</option>' +
                '<option value="false"' + (val === 'false' ? ' selected' : '') + '>No</option>' +
                '</select>';
        } else if (field.type === 'text') {
            controlHtml =
                '<textarea class="cc-textarea cc-input-sm spec-live-input" rows="2" id="' + id + '" name="spec_' + escapeHtml(field.name) + '" data-label="' + escapeHtml(field.label) + '" data-unit="">' + escapeHtml(val) + '</textarea>';
        } else {
            const inputType = (field.type === 'int' || field.type === 'decimal') ? 'number' : 'text';
            const stepAttr = field.type === 'decimal' ? ' step="0.01"' : '';
            const minAttr = (field.type === 'int' || field.type === 'decimal') ? ' min="0"' : '';
            const roundedClass = unitSuffix ? ' rounded-r-none' : '';
            const inputEl =
                '<input type="' + inputType + '"' + stepAttr + minAttr +
                ' class="cc-input cc-input-sm spec-live-input' + roundedClass + '" id="' + id +
                '" name="spec_' + escapeHtml(field.name) +
                '" value="' + escapeHtml(val) +
                '" placeholder="' + escapeHtml(field.placeholder || 'Leave blank if unknown') +
                '" data-label="' + escapeHtml(field.label) +
                '" data-unit="' + escapeHtml(field.unit || '') + '">';
            controlHtml = unitSuffix
                ? '<div class="flex items-stretch">' + inputEl + unitSuffix + '</div>'
                : inputEl;
        }

        const hasVal = val !== undefined && val !== null && String(val).trim() !== '';
        const statusPill = hasVal
            ? '<span class="text-[10px] spec-status-badge cc-badge cc-badge-neutral" data-spec-status-for="' + escapeHtml(field.name) + '">Manually entered</span>'
            : '<span class="text-[10px] spec-status-badge" data-spec-status-for="' + escapeHtml(field.name) + '"></span>';

        return (
            '<div>' +
            '<div class="flex flex-wrap items-center justify-between gap-1 mb-1">' +
            '<label for="' + id + '" class="cc-label mb-0">' +
            escapeHtml(field.label) + criticalBadge +
            '</label>' +
            statusPill +
            '</div>' +
            controlHtml +
            '</div>'
        );
    }

    if (categorySelect && schemaBaseUrl && dynamicSpecsContainer) {
        categorySelect.addEventListener('change', async () => {
            const catId = categorySelect.value;
            if (!catId) return;
            const prevValues = readCurrentSpecValues();
            const url = schemaBaseUrl.replace('/0/', '/' + encodeURIComponent(catId) + '/');
            try {
                const resp = await fetch(url, { headers: { 'Accept': 'application/json' } });
                if (!resp.ok) return;
                const data = await resp.json();
                const html = (data.fields || [])
                    .map((f) => renderSpecFieldControl(f, prevValues[f.name] || ''))
                    .join('');
                dynamicSpecsContainer.innerHTML = html || '<div class="sm:col-span-2 text-xs text-muted">No category-specific fields defined. Use custom specifications below.</div>';
                updateLivePreview();
            } catch (err) {
                console.warn('Could not load category spec schema:', err);
            }
        });
    }

    function appendCustomSpecRow(groupVal, keyVal, valVal, unitVal) {
        if (!customSpecContainer) return;
        const row = document.createElement('div');
        row.className = 'grid grid-cols-12 gap-2 items-center custom-spec-row';
        row.innerHTML =
            '<div class="col-span-3"><input type="text" name="custom_spec_group[]" class="cc-input cc-input-sm" placeholder="Group (e.g. Cooling)" value="' + escapeHtml(groupVal || 'Additional') + '"></div>' +
            '<div class="col-span-4"><input type="text" name="custom_spec_key[]" class="cc-input cc-input-sm" placeholder="Spec Name" value="' + escapeHtml(keyVal || '') + '"></div>' +
            '<div class="col-span-3"><input type="text" name="custom_spec_value[]" class="cc-input cc-input-sm" placeholder="Value" value="' + escapeHtml(valVal || '') + '"></div>' +
            '<div class="col-span-1"><input type="text" name="custom_spec_unit[]" class="cc-input cc-input-sm" placeholder="Unit" value="' + escapeHtml(unitVal || '') + '"></div>' +
            '<div class="col-span-1 text-right"><button type="button" class="cc-btn cc-btn-danger cc-btn-sm px-2 btn-remove-custom-spec" title="Remove row"><i data-lucide="x" class="w-3.5 h-3.5"></i></button></div>';
        customSpecContainer.appendChild(row);
        refreshIcons();
    }

    if (addCustomSpecBtn && customSpecContainer) {
        addCustomSpecBtn.addEventListener('click', () => appendCustomSpecRow('Additional', '', '', ''));
        customSpecContainer.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn-remove-custom-spec');
            if (btn) {
                btn.closest('.custom-spec-row').remove();
            }
        });
    }

    function updateLivePreview() {
        const pName = document.getElementById('live-preview-name');
        const pSku = document.getElementById('live-preview-sku');
        const pPrice = document.getElementById('live-preview-price');
        const pStatus = document.getElementById('live-preview-status');
        const pDesc = document.getElementById('live-preview-short-desc');
        const pSpecs = document.getElementById('live-preview-specs');

        if (pName && nameInput) pName.textContent = nameInput.value.trim() || 'Untitled Product';
        if (pSku && skuInput) pSku.textContent = skuInput.value.trim().toUpperCase() || 'AUTO-SKU';
        if (pPrice && priceInput) {
            const num = parseFloat(priceInput.value);
            pPrice.textContent = isNaN(num) ? 'Rs. 0.00' : 'Rs. ' + num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        if (pStatus && statusSelect) {
            const st = statusSelect.value;
            pStatus.textContent = statusSelect.options[statusSelect.selectedIndex]?.text || st;
            pStatus.className = 'cc-badge text-[10px] ' + (st === 'published' ? 'cc-badge-compatible' : (st === 'archived' ? 'cc-badge-neutral' : 'cc-badge-warning'));
        }
        if (pDesc && shortDescInput) {
            pDesc.textContent = shortDescInput.value.trim() || 'Short summary will appear here.';
        }
        if (pSpecs && dynamicSpecsContainer) {
            const badges = [];
            dynamicSpecsContainer.querySelectorAll('.spec-live-input').forEach((el) => {
                const v = (el.value || '').trim();
                if (v && badges.length < 5) {
                    const label = el.dataset.label || '';
                    const unit = el.dataset.unit || '';
                    const formatted = el.tagName === 'SELECT' ? (v === 'true' ? 'Yes' : 'No') : (unit ? v + ' ' + unit : v);
                    badges.push('<span class="cc-badge cc-badge-neutral cc-mono text-[10px]">' + escapeHtml(label) + ': ' + escapeHtml(formatted) + '</span>');
                }
            });
            pSpecs.innerHTML = badges.join(' ') || '<span class="text-xs text-muted">Key hardware highlights appear as specs are filled.</span>';
        }
    }

    [nameInput, skuInput, priceInput, statusSelect, shortDescInput].forEach((el) => {
        if (el) el.addEventListener('input', updateLivePreview);
        if (el) el.addEventListener('change', updateLivePreview);
    });
    if (dynamicSpecsContainer) {
        const onSpecEdited = (e) => {
            const el = e.target.closest('.spec-live-input');
            if (el) {
                el.dataset.manualDirty = 'true';
                const fieldName = (el.name || '').replace(/^spec_/, '');
                if (fieldName) {
                    const hasVal = String(el.value || '').trim() !== '';
                    setFieldStatusBadge(fieldName, hasVal ? 'manual' : '');
                }
            }
            updateLivePreview();
        };
        dynamicSpecsContainer.addEventListener('input', onSpecEdited);
        dynamicSpecsContainer.addEventListener('change', onSpecEdited);
    }

    if (galleryFileInput) {
        galleryFileInput.addEventListener('change', () => {
            const previewImg = document.getElementById('live-preview-image');
            if (previewImg && galleryFileInput.files && galleryFileInput.files[0]) {
                previewImg.src = URL.createObjectURL(galleryFileInput.files[0]);
            }
        });
    }

    let dupTimer = null;
    async function runDuplicateCheck() {
        if (!duplicateCheckUrl || !duplicateBox) return;
        const params = new URLSearchParams({
            name: nameInput ? nameInput.value.trim() : '',
            sku: skuInput ? skuInput.value.trim() : '',
            model_number: modelInput ? modelInput.value.trim() : '',
            category_id: categorySelect ? categorySelect.value : '',
            brand_id: brandSelect ? brandSelect.value : '',
            exclude_id: productId,
        });
        try {
            const resp = await fetch(duplicateCheckUrl + '?' + params.toString());
            if (!resp.ok) return;
            const data = await resp.json();
            const matches = data.matches || [];
            if (!matches.length) {
                duplicateBox.classList.add('hidden');
                duplicateBox.innerHTML = '';
                return;
            }
            const items = matches
                .map((m) => '<li><strong>' + escapeHtml(m.name) + '</strong> (<code class="cc-mono">' + escapeHtml(m.sku) + '</code> - ' + escapeHtml(m.status) + '): ' + escapeHtml(m.reason) + '</li>')
                .join('');
            duplicateBox.innerHTML =
                '<div class="cc-alert cc-alert-warning flex-col mb-4">' +
                '<div class="font-bold flex items-center gap-2"><i data-lucide="triangle-alert" class="w-4 h-4"></i><span>Possible Duplicate Products Detected (review before saving):</span></div>' +
                '<ul class="list-disc pl-5 text-xs space-y-0.5">' + items + '</ul>' +
                '</div>';
            duplicateBox.classList.remove('hidden');
            refreshIcons();
        } catch (err) {
            console.warn('Duplicate check error:', err);
        }
    }

    [nameInput, skuInput, modelInput, categorySelect, brandSelect].forEach((el) => {
        if (!el) return;
        const trigger = () => {
            clearTimeout(dupTimer);
            dupTimer = setTimeout(runDuplicateCheck, 400);
        };
        el.addEventListener('input', trigger);
        el.addEventListener('change', trigger);
    });

    const SPEC_STATUS_STYLES = {
        sourced: { label: 'Sourced', cls: 'cc-badge cc-badge-compatible' },
        needs_verification: { label: 'Needs verification', cls: 'cc-badge cc-badge-tech' },
        conflicting: { label: 'Conflicting sources', cls: 'cc-badge cc-badge-warning' },
        not_found: { label: 'Not found', cls: 'cc-badge cc-badge-neutral' },
        manual: { label: 'Manually entered', cls: 'cc-badge cc-badge-neutral' },
    };

    function setFieldStatusBadge(fieldName, statusKey) {
        const badge = productForm.querySelector('[data-spec-status-for="' + fieldName + '"]');
        if (!badge) return;
        const meta = SPEC_STATUS_STYLES[statusKey];
        if (!meta) {
            badge.textContent = '';
            badge.className = 'text-[10px] spec-status-badge';
            return;
        }
        badge.textContent = meta.label;
        badge.className = 'text-[10px] spec-status-badge ' + meta.cls;
    }

    const aiBtn = document.getElementById('btn-ai-research');
    const aiRefUrlInput = document.getElementById('id_ai_reference_url');
    const aiResultsPanel = document.getElementById('ai-research-results');
    const aiDraftInput = document.getElementById('id_ai_draft_id');
    const aiApprovalBox = document.getElementById('ai-approval-confirm-box');
    const aiApprovalCheckbox = document.getElementById('id_confirm_ai_approval');

    async function executeAiResearch(confirmedMatch = false) {
        if (!aiBtn || !aiResearchUrl || !aiResultsPanel) return;
        const prodName = nameInput ? nameInput.value.trim() : '';
        const catId = categorySelect ? categorySelect.value : '';
        if (!prodName || !catId) {
            aiResultsPanel.innerHTML =
                '<div class="cc-alert cc-alert-warning text-xs">' +
                'Enter both a <strong>Product Name</strong> and <strong>Category</strong> above before running AI research.' +
                '</div>';
            aiResultsPanel.classList.remove('hidden');
            return;
        }

        const selectedBrandText = brandSelect && brandSelect.value
            ? (brandSelect.options[brandSelect.selectedIndex]?.text || '')
            : (newBrandInput ? newBrandInput.value.trim() : '');

        aiBtn.disabled = true;
        const origHtml = aiBtn.innerHTML;
        aiBtn.textContent = 'Researching online...';

        try {
            const resp = await fetch(aiResearchUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify({
                    product_name: prodName,
                    category_id: catId,
                    brand_name: selectedBrandText,
                    model_number: modelInput ? modelInput.value.trim() : '',
                    reference_url: aiRefUrlInput ? aiRefUrlInput.value.trim() : '',
                    product_id: productId || null,
                    confirmed_match: confirmedMatch,
                }),
            });
            const data = await resp.json();
            if (!resp.ok) {
                aiResultsPanel.innerHTML =
                    '<div class="cc-alert cc-alert-danger text-xs"><div><strong>Research Stopped:</strong> ' +
                    escapeHtml(data.error || 'Request failed.') + ' Enter specifications manually below.</div></div>';
                aiResultsPanel.classList.remove('hidden');
                return;
            }

            renderAiResults(data);
        } catch (err) {
            aiResultsPanel.innerHTML =
                '<div class="cc-alert cc-alert-warning text-xs">AI research service could not be reached right now. Continue entering specifications manually below.</div>';
            aiResultsPanel.classList.remove('hidden');
        } finally {
            aiBtn.disabled = false;
            aiBtn.innerHTML = origHtml;
            refreshIcons();
        }
    }

    if (aiBtn && aiResearchUrl && aiResultsPanel) {
        aiBtn.addEventListener('click', () => executeAiResearch(false));
    }

    function formatSpecPreviewVal(v) {
        if (Array.isArray(v)) return v.join(', ');
        if (v && typeof v === 'object') return JSON.stringify(v);
        if (v === true) return 'Yes';
        if (v === false) return 'No';
        return String(v);
    }

    function applySingleSpecField(fieldName, value, statusKey = 'manual') {
        const el = productForm.querySelector('[name="spec_' + fieldName + '"]');
        if (!el) return;
        if (el.tagName === 'SELECT') {
            el.value = value === true ? 'true' : (value === false ? 'false' : String(value));
        } else if (Array.isArray(value)) {
            el.value = value.join(', ');
        } else if (value && typeof value === 'object') {
            el.value = JSON.stringify(value);
        } else {
            el.value = String(value);
        }
        el.dataset.manualDirty = statusKey === 'manual' ? 'true' : 'false';
        setFieldStatusBadge(fieldName, statusKey);
        updateLivePreview();
    }

    function renderAiResults(data) {
        if (!aiResultsPanel) return;

        // Keep approval hidden unless staff explicitly applies an exact draft
        if (aiDraftInput) aiDraftInput.value = '';
        if (aiApprovalBox) aiApprovalBox.classList.add('hidden');
        if (aiApprovalCheckbox) aiApprovalCheckbox.checked = false;

        if (!data.available) {
            aiResultsPanel.innerHTML =
                '<div class="cc-alert cc-alert-info text-xs">' +
                '<div class="flex items-center gap-2"><i data-lucide="info" class="w-4 h-4 shrink-0"></i><span>' +
                escapeHtml(data.summary_note || 'AI specification research is unavailable. Enter specifications manually below.') +
                '</span></div></div>';
            aiResultsPanel.classList.remove('hidden');
            refreshIcons();
            return;
        }

        // Sync per-field status indicators when user hasn't manually edited a field
        Object.entries(data.field_statuses || {}).forEach(([fname, st]) => {
            const el = productForm.querySelector('[name="spec_' + fname + '"]');
            if (el && (el.dataset.manualDirty === 'true' || String(el.value || '').trim() !== '')) {
                return;
            }
            setFieldStatusBadge(fname, st);
        });

        // Situation 2: Possible typo or ambiguous product query -> ask confirmation before treating as identified
        if (data.match_status === 'ambiguous') {
            const suggestions = data.suggested_corrections || [];
            const suggestionsHtml = suggestions.map((s, idx) => {
                const urlHtml = s.url
                    ? ' &mdash; <a href="' + escapeHtml(s.url) + '" target="_blank" rel="noopener noreferrer" class="text-tech-ink hover:underline">Reference</a>'
                    : '';
                return (
                    '<div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface p-2.5">' +
                    '<div class="text-xs min-w-0">' +
                    '<div class="font-bold text-ink">' + escapeHtml(s.name) + '</div>' +
                    '<div class="text-[11px] text-muted">' + escapeHtml(s.reason || 'Suggested exact product match') + urlHtml + '</div>' +
                    '</div>' +
                    '<button type="button" class="cc-btn cc-btn-tech cc-btn-sm py-1 px-2.5 text-xs btn-confirm-suggestion" data-suggestion-idx="' + idx + '">' +
                    'Confirm &amp; Research</button>' +
                    '</div>'
                );
            }).join('');

            aiResultsPanel.innerHTML =
                '<div class="cc-alert cc-alert-warning flex-col items-stretch gap-2.5 text-xs">' +
                '<div class="font-bold flex items-center gap-2"><i data-lucide="help-circle" class="w-4 h-4 shrink-0"></i><span>Possible Typo or Ambiguous Product Name</span></div>' +
                '<p>' + escapeHtml(data.summary_note || 'No specs were auto-populated because the entered name did not match unambiguously.') + '</p>' +
                (suggestionsHtml ? '<div class="space-y-2">' + suggestionsHtml + '</div>' : '') +
                '<div class="flex justify-end"><button type="button" id="btn-keep-manual-entry" class="cc-btn cc-btn-secondary cc-btn-sm py-1 px-2.5 text-xs">Keep My Name &amp; Enter Manually</button></div>' +
                '</div>';
            aiResultsPanel.classList.remove('hidden');
            refreshIcons();

            aiResultsPanel.querySelectorAll('.btn-confirm-suggestion').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const idx = Number(btn.dataset.suggestionIdx);
                    const picked = suggestions[idx];
                    if (picked && picked.name && nameInput) {
                        nameInput.value = picked.name;
                        updateLivePreview();
                        executeAiResearch(true);
                    }
                });
            });
            const keepManualBtn = document.getElementById('btn-keep-manual-entry');
            if (keepManualBtn) {
                keepManualBtn.addEventListener('click', () => {
                    aiResultsPanel.innerHTML = '<div class="text-xs text-muted">Keeping entered product name. Enter technical specifications manually below.</div>';
                });
            }
            return;
        }

        // Situation 3: Product not confidently identified -> no guessed specs, keep manual entry open
        if (data.match_status === 'not_found') {
            aiResultsPanel.innerHTML =
                '<div class="cc-alert cc-alert-warning flex-col items-start gap-1.5 text-xs">' +
                '<div class="font-bold flex items-center gap-2"><i data-lucide="alert-circle" class="w-4 h-4 shrink-0"></i><span>Product not confidently identified.</span></div>' +
                '<p>' + escapeHtml(data.summary_note || 'No technical specifications were guessed or populated. You may enter specifications manually below and save normally.') + '</p>' +
                '</div>';
            aiResultsPanel.classList.remove('hidden');
            refreshIcons();
            return;
        }

        // Situation 1: Exact product found -> display reviewable specs, conflicts, and sources
        const badgeMap = {
            verified_manufacturer: 'cc-badge-compatible',
            mixed_sources: 'cc-badge-tech',
            partial: 'cc-badge-warning',
            unverified: 'cc-badge-incompatible',
        };
        const vBadge = badgeMap[data.verification_status] || 'cc-badge-neutral';

        const proposedEntries = Object.entries(data.proposed_specs || {});
        const fieldStatuses = data.field_statuses || {};
        const proposedHtml = proposedEntries.length
            ? proposedEntries.map(([k, v]) => {
                const st = fieldStatuses[k] || 'needs_verification';
                const stMeta = SPEC_STATUS_STYLES[st] || SPEC_STATUS_STYLES.needs_verification;
                return (
                    '<li class="flex flex-wrap items-center gap-2 py-0.5">' +
                    '<code class="cc-mono text-accent-ink">' + escapeHtml(k) + '</code>: ' +
                    '<strong>' + escapeHtml(formatSpecPreviewVal(v)) + '</strong>' +
                    '<span class="' + stMeta.cls + ' text-[10px]">' + escapeHtml(stMeta.label) + '</span>' +
                    '</li>'
                );
            }).join('')
            : '<li class="text-muted">No verified typed specs proposed.</li>';

        const conflictHtml = (data.conflicting_fields && data.conflicting_fields.length)
            ? '<div class="cc-alert cc-alert-warning flex-col items-stretch text-xs mt-2"><strong>Conflicting Sources Detected (choose carefully or enter manually):</strong><div class="space-y-2 mt-1.5">' +
              data.conflicting_fields.map((c, cIdx) => {
                  const valBtns = (c.values || []).map((val, vIdx) => (
                      '<button type="button" class="cc-btn cc-btn-secondary cc-btn-sm py-0.5 px-2 text-[11px] btn-pick-conflict" data-field="' + escapeHtml(c.field) + '" data-value="' + escapeHtml(String(val)) + '">' +
                      'Use: ' + escapeHtml(String(val)) +
                      '</button>'
                  )).join(' ');
                  return (
                      '<div class="rounded-lg border border-border bg-surface p-2">' +
                      '<div><strong>' + escapeHtml(c.label || c.field) + '</strong>: ' + escapeHtml((c.values || []).join(' vs ')) +
                      (c.note ? ' &mdash; <span class="text-muted">' + escapeHtml(c.note) + '</span>' : '') + '</div>' +
                      (valBtns ? '<div class="mt-1.5 flex flex-wrap gap-1.5">' + valBtns + '</div>' : '') +
                      '</div>'
                  );
              }).join('') +
              '</div></div>'
            : '';

        const missingHtml = (data.missing_fields && data.missing_fields.length)
            ? '<div class="text-xs text-muted mt-1.5"><strong>Not found / Unverified (left unknown):</strong> ' +
              data.missing_fields.map((m) => '<code class="cc-mono">' + escapeHtml(m) + '</code>').join(', ') + '</div>'
            : '';

        const rejectedHtml = (data.rejected_fields && data.rejected_fields.length)
            ? '<div class="text-xs text-red-400 mt-1.5"><strong>Safety Filter Notices:</strong> ' + data.rejected_fields.map(escapeHtml).join('; ') + '</div>'
            : '';

        const sourcesHtml = (data.sources && data.sources.length)
            ? '<div class="mt-2"><strong class="text-xs text-ink">Attributed Sources:</strong><ul class="space-y-1 text-xs mt-1">' +
              data.sources.map((s) => {
                  const tag = s.origin_type === 'manufacturer'
                      ? '<span class="cc-badge cc-badge-compatible text-[10px] mr-1.5">Manufacturer</span>'
                      : '<span class="cc-badge cc-badge-neutral text-[10px] mr-1.5">Third-Party</span>';
                  return '<li>' + tag + '<a href="' + escapeHtml(s.url) + '" target="_blank" rel="noopener noreferrer" class="text-tech-ink hover:underline">' + escapeHtml(s.title || s.url) + '</a></li>';
              }).join('') +
              '</ul></div>'
            : '<div class="cc-alert cc-alert-danger text-xs mt-2 py-2">No verified source URL provided; verify every value manually before saving.</div>';

        const identifiedBanner = data.identified_name
            ? '<div class="text-xs text-ink font-semibold">Matched Product: <span class="text-accent-ink">' + escapeHtml(data.identified_name) + '</span></div>'
            : '';

        aiResultsPanel.innerHTML =
            '<div class="cc-panel-elevated p-4 space-y-2.5">' +
            '<div class="flex flex-wrap justify-between items-center gap-2">' +
            '<div class="flex flex-wrap gap-1.5"><span class="cc-badge ' + vBadge + '">' + escapeHtml(data.verification_label) + '</span>' +
            '<span class="cc-badge cc-badge-neutral cc-mono">Confidence: ' + escapeHtml(data.confidence) + '</span></div>' +
            '<div class="flex flex-wrap gap-1.5">' +
            '<button type="button" class="cc-btn cc-btn-success cc-btn-sm" id="btn-apply-ai-empty"><i data-lucide="circle-check" class="w-3.5 h-3.5"></i><span>Populate Empty Fields</span></button>' +
            '<button type="button" class="cc-btn cc-btn-secondary cc-btn-sm" id="btn-apply-ai-all">Overwrite Matching Fields</button>' +
            '<button type="button" class="cc-btn cc-btn-secondary cc-btn-sm" id="btn-discard-ai-draft">Discard</button>' +
            '</div></div>' +
            identifiedBanner +
            (data.summary_note ? '<p class="text-xs text-muted">' + escapeHtml(data.summary_note) + '</p>' : '') +
            '<div class="text-xs text-ink"><strong>Researched Specifications (Editable Draft #' + escapeHtml(data.draft_id) + '):</strong><ul class="mt-1 space-y-0.5">' + proposedHtml + '</ul></div>' +
            conflictHtml + missingHtml + rejectedHtml + sourcesHtml +
            '</div>';
        aiResultsPanel.classList.remove('hidden');
        refreshIcons();

        const applyEmptyBtn = document.getElementById('btn-apply-ai-empty');
        const applyAllBtn = document.getElementById('btn-apply-ai-all');
        const discardBtn = document.getElementById('btn-discard-ai-draft');

        if (applyEmptyBtn) {
            applyEmptyBtn.addEventListener('click', () => applyDraftToForm(data, false));
        }
        if (applyAllBtn) {
            applyAllBtn.addEventListener('click', () => applyDraftToForm(data, true));
        }
        aiResultsPanel.querySelectorAll('.btn-pick-conflict').forEach((btn) => {
            btn.addEventListener('click', () => {
                const fname = btn.dataset.field;
                const val = btn.dataset.value;
                if (fname) {
                    applySingleSpecField(fname, val, 'manual');
                    if (aiDraftInput) aiDraftInput.value = data.draft_id || '';
                    if (aiApprovalBox) aiApprovalBox.classList.remove('hidden');
                }
            });
        });
        if (discardBtn) {
            discardBtn.addEventListener('click', async () => {
                if (aiDiscardUrlTemplate && data.draft_id) {
                    const url = aiDiscardUrlTemplate.replace('/0/', '/' + encodeURIComponent(data.draft_id) + '/');
                    await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() } });
                }
                if (aiDraftInput) aiDraftInput.value = '';
                if (aiApprovalBox) aiApprovalBox.classList.add('hidden');
                if (aiApprovalCheckbox) aiApprovalCheckbox.checked = false;
                aiResultsPanel.innerHTML = '<div class="text-xs text-muted">AI specification draft discarded. Enter specifications manually below.</div>';
            });
        }
    }

    function applyDraftToForm(data, overwriteExisting = false) {
        if (!data) return;
        const proposed = data.proposed_specs || {};
        const fieldStatuses = data.field_statuses || {};
        let skippedManualCount = 0;

        Object.entries(proposed).forEach(([fieldName, value]) => {
            const el = productForm.querySelector('[name="spec_' + fieldName + '"]');
            if (!el) return;
            const currentVal = String(el.value || '').trim();
            const isManuallyEntered = el.dataset.manualDirty === 'true' || currentVal !== '';
            if (!overwriteExisting && isManuallyEntered) {
                skippedManualCount += 1;
                return;
            }
            const statusKey = fieldStatuses[fieldName] || 'needs_verification';
            applySingleSpecField(fieldName, value, statusKey);
        });

        Object.entries(fieldStatuses).forEach(([fieldName, st]) => {
            if (Object.prototype.hasOwnProperty.call(proposed, fieldName)) return;
            const el = productForm.querySelector('[name="spec_' + fieldName + '"]');
            if (!el || el.dataset.manualDirty === 'true' || String(el.value || '').trim() !== '') return;
            setFieldStatusBadge(fieldName, st);
        });

        const customSpecs = data.custom_specs || {};
        Object.entries(customSpecs).forEach(([k, v]) => {
            const existingKeys = Array.from(productForm.querySelectorAll('input[name="custom_spec_key[]"]')).map((inp) => inp.value.trim().toLowerCase());
            if (!existingKeys.includes(k.trim().toLowerCase())) {
                appendCustomSpecRow('AI Draft', k, v, '');
            }
        });

        if (aiDraftInput) aiDraftInput.value = data.draft_id || '';
        if (aiApprovalBox) aiApprovalBox.classList.remove('hidden');
        if (aiApprovalCheckbox) aiApprovalCheckbox.checked = true;
        if (skippedManualCount > 0 && !overwriteExisting) {
            const noteId = 'ai-preserved-manual-note';
            let existingNote = document.getElementById(noteId);
            if (!existingNote && aiResultsPanel) {
                existingNote = document.createElement('div');
                existingNote.id = noteId;
                existingNote.className = 'cc-alert cc-alert-info text-xs mt-2';
                aiResultsPanel.appendChild(existingNote);
            }
            if (existingNote) {
                existingNote.textContent = 'Preserved ' + skippedManualCount + ' manually entered field(s). Use "Overwrite Matching Fields" if you want to replace them.';
            }
        }
        updateLivePreview();
    }

    updateLivePreview();
})();
