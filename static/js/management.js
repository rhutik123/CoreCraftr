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

        return (
            '<div>' +
            '<label for="' + id + '" class="cc-label">' +
            escapeHtml(field.label) + criticalBadge +
            '</label>' +
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
        dynamicSpecsContainer.addEventListener('input', updateLivePreview);
        dynamicSpecsContainer.addEventListener('change', updateLivePreview);
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

    const aiBtn = document.getElementById('btn-ai-research');
    const aiRefUrlInput = document.getElementById('id_ai_reference_url');
    const aiResultsPanel = document.getElementById('ai-research-results');
    const aiDraftInput = document.getElementById('id_ai_draft_id');
    const aiApprovalBox = document.getElementById('ai-approval-confirm-box');
    const aiApprovalCheckbox = document.getElementById('id_confirm_ai_approval');

    if (aiBtn && aiResearchUrl && aiResultsPanel) {
        aiBtn.addEventListener('click', async () => {
            const prodName = nameInput ? nameInput.value.trim() : '';
            const catId = categorySelect ? categorySelect.value : '';
            if (!prodName || !catId) {
                aiResultsPanel.innerHTML = '<div class="cc-alert cc-alert-warning text-xs">Enter a Product Name and Category first before researching specifications.</div>';
                aiResultsPanel.classList.remove('hidden');
                return;
            }

            const selectedBrandText = brandSelect && brandSelect.value
                ? (brandSelect.options[brandSelect.selectedIndex]?.text || '')
                : (newBrandInput ? newBrandInput.value.trim() : '');

            aiBtn.disabled = true;
            const origText = aiBtn.innerHTML;
            aiBtn.textContent = 'Researching...';

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
                    '<div class="cc-alert cc-alert-warning text-xs">AI service unreachable right now. Enter specifications manually below.</div>';
                aiResultsPanel.classList.remove('hidden');
            } finally {
                aiBtn.disabled = false;
                aiBtn.innerHTML = origText;
                refreshIcons();
            }
        });
    }

    function renderAiResults(data) {
        if (!aiResultsPanel) return;
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

        const badgeMap = {
            verified_manufacturer: 'cc-badge-compatible',
            mixed_sources: 'cc-badge-tech',
            partial: 'cc-badge-warning',
            unverified: 'cc-badge-incompatible',
        };
        const vBadge = badgeMap[data.verification_status] || 'cc-badge-neutral';

        const proposedEntries = Object.entries(data.proposed_specs || {});
        const proposedHtml = proposedEntries.length
            ? proposedEntries.map(([k, v]) => '<li><code class="cc-mono text-accent-ink">' + escapeHtml(k) + '</code>: <strong>' + escapeHtml(Array.isArray(v) ? v.join(', ') : (typeof v === 'object' ? JSON.stringify(v) : v)) + '</strong></li>').join('')
            : '<li class="text-muted">No verified typed specs proposed.</li>';

        const conflictHtml = (data.conflicting_fields && data.conflicting_fields.length)
            ? '<div class="cc-alert cc-alert-warning flex-col text-xs mt-3"><strong>Conflicting Sources Detected (resolve manually):</strong><ul class="list-disc pl-5 mt-1">' +
              data.conflicting_fields.map((c) => '<li><strong>' + escapeHtml(c.label || c.field) + '</strong>: ' + escapeHtml((c.values || []).join(' vs ')) + ' — ' + escapeHtml(c.note) + '</li>').join('') +
              '</ul></div>'
            : '';

        const missingHtml = (data.missing_fields && data.missing_fields.length)
            ? '<div class="text-xs text-muted mt-2"><strong>Unverified / Missing Fields (kept unknown):</strong> ' +
              data.missing_fields.map((m) => '<code class="cc-mono">' + escapeHtml(m) + '</code>').join(', ') + '</div>'
            : '';

        const rejectedHtml = (data.rejected_fields && data.rejected_fields.length)
            ? '<div class="text-xs text-red-400 mt-2"><strong>Safety Filter Notices:</strong> ' + data.rejected_fields.map(escapeHtml).join('; ') + '</div>'
            : '';

        const sourcesHtml = (data.sources && data.sources.length)
            ? '<div class="mt-3"><strong class="text-xs text-ink">Attributed Sources:</strong><ul class="space-y-1 text-xs mt-1">' +
              data.sources.map((s) => {
                  const tag = s.origin_type === 'manufacturer'
                      ? '<span class="cc-badge cc-badge-compatible text-[10px] mr-1.5">Manufacturer</span>'
                      : '<span class="cc-badge cc-badge-neutral text-[10px] mr-1.5">Third-Party</span>';
                  return '<li>' + tag + '<a href="' + escapeHtml(s.url) + '" target="_blank" rel="noopener noreferrer" class="text-tech-ink hover:underline">' + escapeHtml(s.title || s.url) + '</a></li>';
              }).join('') +
              '</ul></div>'
            : '<div class="cc-alert cc-alert-danger text-xs mt-2 py-2">No verified source URL provided; review carefully before saving.</div>';

        aiResultsPanel.innerHTML =
            '<div class="cc-panel-elevated p-4 space-y-2.5">' +
            '<div class="flex flex-wrap justify-between items-center gap-2">' +
            '<div class="flex flex-wrap gap-1.5"><span class="cc-badge ' + vBadge + '">' + escapeHtml(data.verification_label) + '</span>' +
            '<span class="cc-badge cc-badge-neutral cc-mono">Confidence: ' + escapeHtml(data.confidence) + '</span></div>' +
            '<div class="flex gap-2">' +
            '<button type="button" class="cc-btn cc-btn-success cc-btn-sm" id="btn-apply-ai-draft"><i data-lucide="circle-check" class="w-3.5 h-3.5"></i><span>Populate Editable Form Fields</span></button>' +
            '<button type="button" class="cc-btn cc-btn-secondary cc-btn-sm" id="btn-discard-ai-draft">Discard</button>' +
            '</div></div>' +
            (data.summary_note ? '<p class="text-xs text-muted">' + escapeHtml(data.summary_note) + '</p>' : '') +
            '<div class="text-xs text-ink"><strong>Suggested Specifications (Editable Draft #' + escapeHtml(data.draft_id) + '):</strong><ul class="list-disc pl-5 mt-1 space-y-0.5">' + proposedHtml + '</ul></div>' +
            conflictHtml + missingHtml + rejectedHtml + sourcesHtml +
            '</div>';
        aiResultsPanel.classList.remove('hidden');
        refreshIcons();

        const applyBtn = document.getElementById('btn-apply-ai-draft');
        const discardBtn = document.getElementById('btn-discard-ai-draft');

        if (applyBtn) {
            applyBtn.addEventListener('click', () => applyDraftToForm(data));
        }
        if (discardBtn) {
            discardBtn.addEventListener('click', async () => {
                if (aiDiscardUrlTemplate && data.draft_id) {
                    const url = aiDiscardUrlTemplate.replace('/0/', '/' + encodeURIComponent(data.draft_id) + '/');
                    await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() } });
                }
                if (aiDraftInput) aiDraftInput.value = '';
                if (aiApprovalBox) aiApprovalBox.classList.add('hidden');
                if (aiApprovalCheckbox) aiApprovalCheckbox.checked = false;
                aiResultsPanel.innerHTML = '<div class="text-xs text-muted">AI specification draft discarded.</div>';
            });
        }
    }

    function applyDraftToForm(data) {
        if (!data) return;
        const proposed = data.proposed_specs || {};
        Object.entries(proposed).forEach(([fieldName, value]) => {
            const el = productForm.querySelector('[name="spec_' + fieldName + '"]');
            if (!el) return;
            if (el.tagName === 'SELECT') {
                el.value = value === true ? 'true' : (value === false ? 'false' : '');
            } else if (Array.isArray(value)) {
                el.value = value.join(', ');
            } else if (value && typeof value === 'object') {
                el.value = JSON.stringify(value);
            } else {
                el.value = String(value);
            }
        });

        const customSpecs = data.custom_specs || {};
        Object.entries(customSpecs).forEach(([k, v]) => {
            appendCustomSpecRow('AI Draft', k, v, '');
        });

        if (aiDraftInput) aiDraftInput.value = data.draft_id || '';
        if (aiApprovalBox) aiApprovalBox.classList.remove('hidden');
        if (aiApprovalCheckbox) aiApprovalCheckbox.checked = true;
        updateLivePreview();
    }

    updateLivePreview();
})();
