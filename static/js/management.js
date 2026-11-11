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

    // Dynamic Category Spec Rendering + Live Preview + Duplicate Check + AI Research
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

    // Collect currently rendered spec field values before switching categories
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
            ? '<span class="badge bg-warning text-dark ms-1 spec-critical-badge">Compatibility</span>'
            : '';
        const unitSuffix = field.unit
            ? '<span class="input-group-text">' + escapeHtml(field.unit) + '</span>'
            : '';

        let controlHtml = '';
        if (field.type === 'bool') {
            controlHtml =
                '<select class="form-select form-select-sm spec-live-input" id="' + id + '" name="spec_' + escapeHtml(field.name) + '" data-label="' + escapeHtml(field.label) + '" data-unit="">' +
                '<option value=""' + (val === '' ? ' selected' : '') + '>Unknown / Unspecified</option>' +
                '<option value="true"' + (val === 'true' ? ' selected' : '') + '>Yes</option>' +
                '<option value="false"' + (val === 'false' ? ' selected' : '') + '>No</option>' +
                '</select>';
        } else if (field.type === 'text') {
            controlHtml =
                '<textarea class="form-control form-control-sm spec-live-input" rows="2" id="' + id + '" name="spec_' + escapeHtml(field.name) + '" data-label="' + escapeHtml(field.label) + '" data-unit="">' + escapeHtml(val) + '</textarea>';
        } else {
            const inputType = (field.type === 'int') ? 'number' : (field.type === 'decimal' ? 'number' : 'text');
            const stepAttr = field.type === 'decimal' ? ' step="0.01"' : '';
            const minAttr = (field.type === 'int' || field.type === 'decimal') ? ' min="0"' : '';
            const inputEl =
                '<input type="' + inputType + '"' + stepAttr + minAttr +
                ' class="form-control form-control-sm spec-live-input" id="' + id +
                '" name="spec_' + escapeHtml(field.name) +
                '" value="' + escapeHtml(val) +
                '" placeholder="' + escapeHtml(field.placeholder || 'Leave blank if unknown') +
                '" data-label="' + escapeHtml(field.label) +
                '" data-unit="' + escapeHtml(field.unit || '') + '">';
            controlHtml = unitSuffix
                ? '<div class="input-group input-group-sm">' + inputEl + unitSuffix + '</div>'
                : inputEl;
        }

        return (
            '<div class="col-md-6">' +
            '<label for="' + id + '" class="form-label form-label-sm fw-semibold mb-1">' +
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
                dynamicSpecsContainer.innerHTML = html || '<div class="col-12 text-muted small">No category-specific fields defined. Use custom specifications below.</div>';
                updateLivePreview();
            } catch (err) {
                console.warn('Could not load category spec schema:', err);
            }
        });
    }

    // Custom key-value specification rows
    function appendCustomSpecRow(groupVal, keyVal, valVal, unitVal) {
        if (!customSpecContainer) return;
        const row = document.createElement('div');
        row.className = 'row g-2 align-items-center mb-2 custom-spec-row';
        row.innerHTML =
            '<div class="col-md-3"><input type="text" name="custom_spec_group[]" class="form-control form-control-sm" placeholder="Group (e.g. Cooling)" value="' + escapeHtml(groupVal || 'Additional') + '"></div>' +
            '<div class="col-md-4"><input type="text" name="custom_spec_key[]" class="form-control form-control-sm" placeholder="Spec Name" value="' + escapeHtml(keyVal || '') + '"></div>' +
            '<div class="col-md-3"><input type="text" name="custom_spec_value[]" class="form-control form-control-sm" placeholder="Value" value="' + escapeHtml(valVal || '') + '"></div>' +
            '<div class="col-md-1"><input type="text" name="custom_spec_unit[]" class="form-control form-control-sm" placeholder="Unit" value="' + escapeHtml(unitVal || '') + '"></div>' +
            '<div class="col-md-1 text-end"><button type="button" class="btn btn-sm btn-outline-danger btn-remove-custom-spec" title="Remove row"><i class="bi bi-x"></i></button></div>';
        customSpecContainer.appendChild(row);
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

    // Real-time live preview updater
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
            pStatus.className = 'badge ' + (st === 'published' ? 'bg-success' : (st === 'archived' ? 'bg-secondary' : 'bg-warning text-dark'));
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
                    badges.push('<span class="badge bg-light text-dark border">' + escapeHtml(label) + ': ' + escapeHtml(formatted) + '</span>');
                }
            });
            pSpecs.innerHTML = badges.join(' ') || '<span class="text-muted small">Key hardware highlights appear as specs are filled.</span>';
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

    // Advisory duplicate product warning check
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
                duplicateBox.classList.add('d-none');
                duplicateBox.innerHTML = '';
                return;
            }
            const items = matches
                .map((m) => '<li><strong>' + escapeHtml(m.name) + '</strong> (' + escapeHtml(m.sku) + ' - ' + escapeHtml(m.status) + '): ' + escapeHtml(m.reason) + '</li>')
                .join('');
            duplicateBox.innerHTML =
                '<div class="alert alert-warning mb-3">' +
                '<strong><i class="bi bi-exclamation-triangle me-1"></i>Possible Duplicate Products Detected (review before saving):</strong>' +
                '<ul class="mb-0 mt-1 small">' + items + '</ul>' +
                '</div>';
            duplicateBox.classList.remove('d-none');
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

    // AI Product Specification Research Assistant
    const aiBtn = document.getElementById('btn-ai-research');
    const aiRefUrlInput = document.getElementById('id_ai_reference_url');
    const aiResultsPanel = document.getElementById('ai-research-results');
    const aiDraftInput = document.getElementById('id_ai_draft_id');
    const aiApprovalBox = document.getElementById('ai-approval-confirm-box');
    const aiApprovalCheckbox = document.getElementById('id_confirm_ai_approval');
    let lastAiDraftData = null;

    if (aiBtn && aiResearchUrl && aiResultsPanel) {
        aiBtn.addEventListener('click', async () => {
            const prodName = nameInput ? nameInput.value.trim() : '';
            const catId = categorySelect ? categorySelect.value : '';
            if (!prodName || !catId) {
                aiResultsPanel.innerHTML = '<div class="alert alert-warning small mb-0">Enter a Product Name and Category first before researching specifications.</div>';
                aiResultsPanel.classList.remove('d-none');
                return;
            }

            const selectedBrandText = brandSelect && brandSelect.value
                ? (brandSelect.options[brandSelect.selectedIndex]?.text || '')
                : (newBrandInput ? newBrandInput.value.trim() : '');

            aiBtn.disabled = true;
            const origText = aiBtn.innerHTML;
            aiBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Researching...';

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
                        '<div class="alert alert-danger small mb-0"><strong>Research Stopped:</strong> ' +
                        escapeHtml(data.error || 'Request failed.') + ' Enter specifications manually below.</div>';
                    aiResultsPanel.classList.remove('d-none');
                    return;
                }

                lastAiDraftData = data;
                renderAiResults(data);
            } catch (err) {
                aiResultsPanel.innerHTML =
                    '<div class="alert alert-warning small mb-0">AI service unreachable right now. Enter specifications manually below.</div>';
                aiResultsPanel.classList.remove('d-none');
            } finally {
                aiBtn.disabled = false;
                aiBtn.innerHTML = origText;
            }
        });
    }

    function renderAiResults(data) {
        if (!aiResultsPanel) return;
        if (!data.available) {
            aiResultsPanel.innerHTML =
                '<div class="alert alert-secondary small mb-0">' +
                '<i class="bi bi-info-circle me-1"></i>' + escapeHtml(data.summary_note || 'AI specification research is unavailable. Enter specifications manually below.') +
                '</div>';
            aiResultsPanel.classList.remove('d-none');
            return;
        }

        const badgeMap = {
            verified_manufacturer: 'bg-success',
            mixed_sources: 'bg-info text-dark',
            partial: 'bg-warning text-dark',
            unverified: 'bg-danger',
        };
        const vBadge = badgeMap[data.verification_status] || 'bg-secondary';

        const proposedEntries = Object.entries(data.proposed_specs || {});
        const proposedHtml = proposedEntries.length
            ? proposedEntries.map(([k, v]) => '<li><code>' + escapeHtml(k) + '</code>: <strong>' + escapeHtml(Array.isArray(v) ? v.join(', ') : (typeof v === 'object' ? JSON.stringify(v) : v)) + '</strong></li>').join('')
            : '<li class="text-muted">No verified typed specs proposed.</li>';

        const conflictHtml = (data.conflicting_fields && data.conflicting_fields.length)
            ? '<div class="alert alert-warning py-2 px-3 mt-2 mb-2 small"><strong>Conflicting Sources Detected (resolve manually):</strong><ul class="mb-0 mt-1">' +
              data.conflicting_fields.map((c) => '<li><strong>' + escapeHtml(c.label || c.field) + '</strong>: ' + escapeHtml((c.values || []).join(' vs ')) + ' — ' + escapeHtml(c.note) + '</li>').join('') +
              '</ul></div>'
            : '';

        const missingHtml = (data.missing_fields && data.missing_fields.length)
            ? '<div class="small text-muted mt-2"><strong>Unverified / Missing Fields (kept unknown):</strong> ' +
              data.missing_fields.map((m) => '<code>' + escapeHtml(m) + '</code>').join(', ') + '</div>'
            : '';

        const rejectedHtml = (data.rejected_fields && data.rejected_fields.length)
            ? '<div class="small text-danger mt-1"><strong>Safety Filter Notices:</strong> ' + data.rejected_fields.map(escapeHtml).join('; ') + '</div>'
            : '';

        const sourcesHtml = (data.sources && data.sources.length)
            ? '<div class="mt-2"><strong class="small">Attributed Sources:</strong><ul class="list-unstyled small mb-0 mt-1">' +
              data.sources.map((s) => {
                  const tag = s.origin_type === 'manufacturer'
                      ? '<span class="badge bg-success-subtle text-success border border-success-subtle me-1">Manufacturer</span>'
                      : '<span class="badge bg-light text-dark border me-1">Third-Party</span>';
                  return '<li class="mb-1">' + tag + '<a href="' + escapeHtml(s.url) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(s.title || s.url) + '</a></li>';
              }).join('') +
              '</ul></div>'
            : '<div class="alert alert-danger py-1 px-2 small mt-2 mb-1">No verified source URL provided; review carefully before saving.</div>';

        aiResultsPanel.innerHTML =
            '<div class="border rounded p-3 bg-light">' +
            '<div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">' +
            '<div><span class="badge ' + vBadge + ' me-1">' + escapeHtml(data.verification_label) + '</span>' +
            '<span class="badge bg-dark">Confidence: ' + escapeHtml(data.confidence) + '</span></div>' +
            '<div class="d-flex gap-2">' +
            '<button type="button" class="btn btn-sm btn-success" id="btn-apply-ai-draft"><i class="bi bi-check2-circle me-1"></i>Populate Editable Form Fields</button>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" id="btn-discard-ai-draft">Discard</button>' +
            '</div></div>' +
            (data.summary_note ? '<p class="small mb-2">' + escapeHtml(data.summary_note) + '</p>' : '') +
            '<div class="small"><strong>Suggested Specifications (Editable Draft #' + escapeHtml(data.draft_id) + '):</strong><ul class="mb-1 mt-1">' + proposedHtml + '</ul></div>' +
            conflictHtml + missingHtml + rejectedHtml + sourcesHtml +
            '</div>';
        aiResultsPanel.classList.remove('d-none');

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
                if (aiApprovalBox) aiApprovalBox.classList.add('d-none');
                if (aiApprovalCheckbox) aiApprovalCheckbox.checked = false;
                aiResultsPanel.innerHTML = '<div class="text-muted small">AI specification draft discarded.</div>';
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
        if (aiApprovalBox) aiApprovalBox.classList.remove('d-none');
        if (aiApprovalCheckbox) aiApprovalCheckbox.checked = true;
        updateLivePreview();
    }

    updateLivePreview();
})();
