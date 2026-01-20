// Data and configuration
const genres = [
    {id: '28', name: 'Action'},
    {id: '12', name: 'Adventure'},
    {id: '16', name: 'Animation'},
    {id: '35', name: 'Comedy'},
    {id: '80', name: 'Crime'},
    {id: '99', name: 'Documentary'},
    {id: '18', name: 'Drama'},
    {id: '10751', name: 'Family'},
    {id: '14', name: 'Fantasy'},
    {id: '36', name: 'History'},
    {id: '27', name: 'Horror'},
    {id: '10402', name: 'Music'},
    {id: '9648', name: 'Mystery'},
    {id: '10749', name: 'Romance'},
    {id: '878', name: 'Sci-Fi'},
    {id: '10770', name: 'TV Movie'},
    {id: '53', name: 'Thriller'},
    {id: '10752', name: 'War'},
    {id: '37', name: 'Western'}
];

const languages = [
    {code: 'en', name: 'English'},
    {code: 'es', name: 'Spanish'},
    {code: 'fr', name: 'French'},
    {code: 'de', name: 'German'},
    {code: 'it', name: 'Italian'},
    {code: 'ja', name: 'Japanese'},
    {code: 'ko', name: 'Korean'},
    {code: 'zh', name: 'Chinese'},
    {code: 'pt', name: 'Portuguese'},
    {code: 'ru', name: 'Russian'},
    {code: 'hi', name: 'Hindi'},
    {code: 'ar', name: 'Arabic'}
];

let selectedActors = [];
let excludedActors = [];
let selectedStudios = [];
let selectedLanguages = DEFAULT_LANGUAGES || ['en'];  // Use default from backend
let searchTimeout;

// Initialize
document.getElementById('masterUrl').textContent = window.location.origin + '/api/master-list';

// Load last updated timestamp
async function loadLastUpdated() {
    try {
        const response = await fetch('/api/metadata');
        const data = await response.json();
        let displayText = 'Never';
        if (data.lastUpdated) {
            const date = new Date(data.lastUpdated);
            const dateStr = date.toLocaleDateString();
            const timeStr = date.toLocaleTimeString();
            const count = data.totalMovies || 0;
            displayText = `${count} Movies - ${dateStr}  ${timeStr}`;
        }
        document.getElementById('lastUpdated').textContent = displayText;
    } catch (e) {
        console.error('Error loading metadata:', e);
    }
}

// Test API function
async function testAPI() {
    const statusEl = document.getElementById('apiStatus');
    statusEl.textContent = 'Testing...';
    statusEl.className = 'api-status';
    
    try {
        const response = await fetch('/api/test-api');
        const result = await response.json();
        
        if (result.success) {
            statusEl.textContent = '✓ API Working';
            statusEl.className = 'api-status success';
        } else {
            statusEl.textContent = '✗ API Error: ' + result.error;
            statusEl.className = 'api-status error';
        }
        
        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.className = '';
        }, 5000);
    } catch (error) {
        statusEl.textContent = '✗ Connection Error';
        statusEl.className = 'api-status error';
        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.className = '';
        }, 5000);
    }
}

// Refresh cache function
async function refreshCache() {
    const statusEl = document.getElementById('apiStatus');
    statusEl.textContent = 'Refreshing cache...';
    statusEl.className = 'api-status';
    
    try {
        const response = await fetch('/api/refresh-cache', { method: 'POST' });
        const result = await response.json();
        
        if (result.success) {
            statusEl.textContent = '✓ Cache Refreshed';
            statusEl.className = 'api-status success';
            loadLastUpdated();
            loadLists();  // Reload lists to update counts
        } else {
            statusEl.textContent = '✗ Refresh Error: ' + result.error;
            statusEl.className = 'api-status error';
        }
        
        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.className = '';
        }, 5000);
    } catch (error) {
        statusEl.textContent = '✗ Connection Error';
        statusEl.className = 'api-status error';
        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.className = '';
        }, 5000);
    }
}

// Initialize language buttons
function initLanguageButtons() {
    const container = document.getElementById('languageButtons');
    languages.forEach(lang => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'lang-btn';
        // Select default languages from backend
        if (selectedLanguages.includes(lang.code)) {
            btn.classList.add('selected');
        }
        btn.textContent = lang.name;
        btn.dataset.code = lang.code;
        btn.onclick = () => toggleLanguage(lang.code);
        container.appendChild(btn);
    });
}

function toggleLanguage(code) {
    const btn = document.querySelector(`.lang-btn[data-code="${code}"]`);
    if (selectedLanguages.includes(code)) {
        selectedLanguages = selectedLanguages.filter(c => c !== code);
        btn.classList.remove('selected');
    } else {
        selectedLanguages.push(code);
        btn.classList.add('selected');
    }
}

// Initialize genre buttons
function initGenreButtons() {
    const includeContainer = document.getElementById('includeGenres');
    const excludeContainer = document.getElementById('excludeGenres');
    
    genres.forEach(genre => {
        const includeBtn = document.createElement('button');
        includeBtn.type = 'button';
        includeBtn.className = 'genre-btn';
        includeBtn.textContent = genre.name;
        includeBtn.dataset.id = genre.id;
        includeBtn.onclick = () => toggleGenre(genre.id, 'include');
        includeContainer.appendChild(includeBtn);

        const excludeBtn = document.createElement('button');
        excludeBtn.type = 'button';
        excludeBtn.className = 'genre-btn';
        excludeBtn.textContent = genre.name;
        excludeBtn.dataset.id = genre.id;
        excludeBtn.onclick = () => toggleGenre(genre.id, 'exclude');
        
        // Default excluded genres
        if (['99', '10402', '10770', '16'].includes(genre.id)) {
            excludeBtn.classList.add('excluded');
        }
        
        excludeContainer.appendChild(excludeBtn);
    });
}

function toggleGenre(genreId, type) {
    const includeBtn = document.querySelector(`#includeGenres .genre-btn[data-id="${genreId}"]`);
    const excludeBtn = document.querySelector(`#excludeGenres .genre-btn[data-id="${genreId}"]`);
    
    if (type === 'include') {
        if (includeBtn.classList.contains('included')) {
            includeBtn.classList.remove('included');
        } else {
            includeBtn.classList.add('included');
            excludeBtn.classList.remove('excluded');
        }
    } else {
        if (excludeBtn.classList.contains('excluded')) {
            excludeBtn.classList.remove('excluded');
        } else {
            excludeBtn.classList.add('excluded');
            includeBtn.classList.remove('included');
        }
    }
}

// Setup actor autocomplete
function setupActorAutocomplete(inputId, listId, actorArray, isExclude = false) {
    document.getElementById(inputId).addEventListener('input', function(e) {
        clearTimeout(searchTimeout);
        const query = e.target.value.trim();
        
        if (query.length < 2) {
            document.getElementById(listId).innerHTML = '';
            return;
        }

        searchTimeout = setTimeout(async () => {
            try {
                const response = await fetch(`/api/search-person?q=${encodeURIComponent(query)}`);
                const results = await response.json();
                
                const container = document.getElementById(listId);
                container.innerHTML = '';
                
                results.forEach(person => {
                    const div = document.createElement('div');
                    div.className = 'autocomplete-item';
                    div.textContent = `${person.name} [${person.id}]`;
                    div.onclick = function() {
                        if (isExclude) {
                            if (!excludedActors.find(a => a.id === person.id)) {
                                excludedActors.push(person);
                                renderActors();
                            }
                            document.getElementById('excludeActorSearch').value = '';
                            document.getElementById('exclude-autocomplete-list').innerHTML = '';
                        } else {
                            if (!selectedActors.find(a => a.id === person.id)) {
                                selectedActors.push(person);
                                renderActors();
                            }
                            document.getElementById('actorSearch').value = '';
                            document.getElementById('autocomplete-list').innerHTML = '';
                        }
                    };
                    container.appendChild(div);
                });
            } catch (error) {
                console.error('Search error:', error);
            }
        }, 300);
    });
}

// Setup studio autocomplete
function setupStudioAutocomplete() {
    document.getElementById('studioSearch').addEventListener('input', function(e) {
        clearTimeout(searchTimeout);
        const query = e.target.value.trim();
        
        if (query.length < 2) {
            document.getElementById('studio-autocomplete-list').innerHTML = '';
            return;
        }

        searchTimeout = setTimeout(async () => {
            try {
                const response = await fetch(`/api/search-company?q=${encodeURIComponent(query)}`);
                const results = await response.json();
                
                const container = document.getElementById('studio-autocomplete-list');
                container.innerHTML = '';
                
                results.forEach(company => {
                    const div = document.createElement('div');
                    div.className = 'autocomplete-item';
                    div.textContent = `${company.name} [${company.id}]`;
                    div.onclick = function() {
                        if (!selectedStudios.find(s => s.id === company.id)) {
                            selectedStudios.push(company);
                            renderStudios();
                        }
                        document.getElementById('studioSearch').value = '';
                        document.getElementById('studio-autocomplete-list').innerHTML = '';
                    };
                    container.appendChild(div);
                });
            } catch (error) {
                console.error('Search error:', error);
            }
        }, 300);
    });
}

function removeActor(personId, isExclude) {
    if (isExclude) {
        excludedActors = excludedActors.filter(a => a.id !== personId);
    } else {
        selectedActors = selectedActors.filter(a => a.id !== personId);
    }
    renderActors();
}

function renderActors() {
    const includeContainer = document.getElementById('selectedActors');
    const excludeContainer = document.getElementById('excludedActors');
    
    includeContainer.innerHTML = '';
    selectedActors.forEach(actor => {
        const tag = document.createElement('div');
        tag.className = 'actor-tag';
        const removeBtn = document.createElement('span');
        removeBtn.className = 'remove';
        removeBtn.textContent = '×';
        removeBtn.onclick = () => removeActor(actor.id, false);
        tag.innerHTML = `${actor.name} [${actor.id}] `;
        tag.appendChild(removeBtn);
        includeContainer.appendChild(tag);
    });
    
    excludeContainer.innerHTML = '';
    excludedActors.forEach(actor => {
        const tag = document.createElement('div');
        tag.className = 'actor-tag exclude';
        const removeBtn = document.createElement('span');
        removeBtn.className = 'remove';
        removeBtn.textContent = '×';
        removeBtn.onclick = () => removeActor(actor.id, true);
        tag.innerHTML = `${actor.name} [${actor.id}] `;
        tag.appendChild(removeBtn);
        excludeContainer.appendChild(tag);
    });
}

function renderStudios() {
    const container = document.getElementById('selectedStudios');
    container.innerHTML = '';
    selectedStudios.forEach(studio => {
        const tag = document.createElement('div');
        tag.className = 'actor-tag';
        const removeBtn = document.createElement('span');
        removeBtn.className = 'remove';
        removeBtn.textContent = '×';
        removeBtn.onclick = () => removeStudio(studio.id);
        tag.innerHTML = `${studio.name} [${studio.id}] `;
        tag.appendChild(removeBtn);
        container.appendChild(tag);
    });
}

function removeStudio(studioId) {
    selectedStudios = selectedStudios.filter(s => s.id !== studioId);
    renderStudios();
}

// Form submission
document.getElementById('listForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    
    const includeGenres = Array.from(document.querySelectorAll('#includeGenres .genre-btn.included'))
        .map(btn => btn.dataset.id);
    const excludeGenres = Array.from(document.querySelectorAll('#excludeGenres .genre-btn.excluded'))
        .map(btn => btn.dataset.id);
    
    const data = {
        name: document.getElementById('listName').value,
        minRating: parseFloat(document.getElementById('minRating').value) || null,
        minVotes: parseInt(document.getElementById('minVotes').value) || null,
        yearFrom: parseInt(document.getElementById('yearFrom').value) || null,
        yearTo: parseInt(document.getElementById('yearTo').value) || null,
        languages: selectedLanguages,
        includeGenres: includeGenres,
        excludeGenres: excludeGenres,
        titleTerms: document.getElementById('titleTerms').value,
        titleExclude: document.getElementById('titleExclude').value,
        studios: selectedStudios,
        actors: selectedActors,
        excludeActors: excludedActors
    };

    const editingId = document.getElementById('editingListId').value;
    const url = editingId ? `/api/update-list/${editingId}` : '/api/create-list';
    const method = editingId ? 'PUT' : 'POST';

    try {
        const response = await fetch(url, {
            method: method,
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });

        const result = await response.json();
        
        if (result.success) {
            showMainScreen();
            loadLists();
        } else {
            alert('Error: ' + (result.error || 'Unknown error'));
        }
    } catch (error) {
        alert('Error: ' + error.message);
    }
});

// Preview list
async function previewList() {
    const includeGenres = Array.from(document.querySelectorAll('#includeGenres .genre-btn.included'))
        .map(btn => btn.dataset.id);
    const excludeGenres = Array.from(document.querySelectorAll('#excludeGenres .genre-btn.excluded'))
        .map(btn => btn.dataset.id);
    
    const data = {
        minRating: parseFloat(document.getElementById('minRating').value) || null,
        minVotes: parseInt(document.getElementById('minVotes').value) || null,
        yearFrom: parseInt(document.getElementById('yearFrom').value) || null,
        yearTo: parseInt(document.getElementById('yearTo').value) || null,
        languages: selectedLanguages,
        includeGenres: includeGenres,
        excludeGenres: excludeGenres,
        titleTerms: document.getElementById('titleTerms').value,
        titleExclude: document.getElementById('titleExclude').value,
        studios: selectedStudios,
        actors: selectedActors,
        excludeActors: excludedActors
    };

    // Show updating status
    document.getElementById('previewStatus').textContent = 'Updating list...';
    document.getElementById('previewCount').textContent = '';
    document.getElementById('previewResults').style.display = 'none';

    try {
        const response = await fetch('/api/preview-list', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });

        const result = await response.json();
        const movies = result.movies;
        const totalCount = result.totalCount;
        
        movies.sort((a, b) => {
            const yearA = a.year || '0';
            const yearB = b.year || '0';
            return yearA.localeCompare(yearB);
        });

        // Clear updating status and show count
        document.getElementById('previewStatus').textContent = '';
        document.getElementById('previewCount').textContent = `(${totalCount} movies)`;
        
        const listHtml = movies.map(movie => `
            <div class="movie-item">
                <span class="movie-title">${movie.title}</span>
                <span class="movie-year">${movie.year}</span>
            </div>
        `).join('');
        
        document.getElementById('previewList').innerHTML = listHtml;
        document.getElementById('previewResults').style.display = 'block';
    } catch (error) {
        document.getElementById('previewStatus').textContent = '';
        alert('Error loading preview: ' + error.message);
    }
}

// Screen navigation
function showMainScreen() {
    document.getElementById('main-screen').style.display = 'block';
    document.getElementById('form-screen').style.display = 'none';
    loadLastUpdated();
    resetForm();
}

function showFormScreen(editId = null) {
    document.getElementById('main-screen').style.display = 'none';
    document.getElementById('form-screen').style.display = 'block';
    
    if (editId) {
        editList(editId);
    }
}

function resetForm() {
    document.getElementById('listForm').reset();
    document.getElementById('editingListId').value = '';
    document.getElementById('submitBtn').textContent = 'Save';
    document.getElementById('previewResults').style.display = 'none';
    document.getElementById('previewCount').textContent = '';
    selectedActors = [];
    excludedActors = [];
    selectedStudios = [];
    selectedLanguages = DEFAULT_LANGUAGES || ['en'];  // Reset to default
    renderActors();
    renderStudios();
    
    // Reset language buttons
    document.querySelectorAll('.lang-btn').forEach(btn => {
        btn.classList.remove('selected');
        if (selectedLanguages.includes(btn.dataset.code)) {
            btn.classList.add('selected');
        }
    });
    
    document.querySelectorAll('.genre-btn').forEach(btn => {
        btn.classList.remove('included', 'excluded');
    });
    
    // Reset to default excluded genres
    ['99', '10402', '10770', '16'].forEach(genreId => {
        const btn = document.querySelector(`#excludeGenres .genre-btn[data-id="${genreId}"]`);
        if (btn) btn.classList.add('excluded');
    });
}

// Load lists
async function loadLists() {
    const response = await fetch('/api/lists');
    const lists = await response.json();
    
    const container = document.getElementById('listContainer');
    container.innerHTML = '';
    
    if (Object.keys(lists).length === 0) {
        container.innerHTML = '<p style="color: #999;">No lists created yet. Click "New List" to get started!</p>';
        return;
    }
    
    const sortedEntries = Object.entries(lists).sort((a, b) => 
        a[1].name.localeCompare(b[1].name)
    );
    
    sortedEntries.forEach(([id, list]) => {
        const div = document.createElement('div');
        div.className = 'list-item' + (list.enabled === false ? ' disabled' : '');
        
        // Get movie count from cache
        fetch(`/api/list-count/${id}`)
            .then(r => r.json())
            .then(data => {
                const countSpan = div.querySelector('.movie-count-small');
                if (countSpan) {
                    countSpan.textContent = `${data.count}`;
                }
            });
        
        div.innerHTML = `
            <div class="list-info">
                <div class="list-name">
                    <span class="name-bold">${list.name}</span> - <span class="movie-count-small">...</span>
                </div>
            </div>
            <div class="list-actions">
                <input type="checkbox" ${list.enabled !== false ? 'checked' : ''} onchange="toggleList('${id}')" title="Enable/Disable">
                <button class="btn-view" onclick="viewList('${id}')">View</button>
                <button class="btn-edit" onclick="showFormScreen('${id}')">Edit</button>
                <button class="btn-delete" onclick="deleteList('${id}')">Delete</button>
            </div>
        `;
        container.appendChild(div);
    });
}

async function toggleList(id) {
    await fetch(`/api/toggle-list/${id}`, {method: 'POST'});
    loadLists();
}

async function deleteList(id) {
    if (confirm('Are you sure you want to delete this list?')) {
        await fetch(`/api/delete-list/${id}`, {method: 'DELETE'});
        loadLists();
    }
}

function viewList(id) {
    window.open(`/view/${id}`, '_blank');
}

async function editList(id) {
    const response = await fetch(`/api/lists`);
    const lists = await response.json();
    const list = lists[id];
    
    document.getElementById('editingListId').value = id;
    document.getElementById('listName').value = list.name;
    document.getElementById('minRating').value = list.minRating || '';
    document.getElementById('minVotes').value = list.minVotes || '';
    document.getElementById('yearFrom').value = list.yearFrom || '';
    document.getElementById('yearTo').value = list.yearTo || '';
    document.getElementById('titleTerms').value = list.titleTerms || '';
    document.getElementById('titleExclude').value = list.titleExclude || '';
    
    selectedActors = list.actors || [];
    excludedActors = list.excludeActors || [];
    selectedStudios = list.studios || [];
    selectedLanguages = list.languages || DEFAULT_LANGUAGES || ['en'];
    renderActors();
    renderStudios();
    
    // Update language buttons
    document.querySelectorAll('.lang-btn').forEach(btn => {
        btn.classList.remove('selected');
        if (selectedLanguages.includes(btn.dataset.code)) {
            btn.classList.add('selected');
        }
    });
    
    document.querySelectorAll('.genre-btn').forEach(btn => {
        btn.classList.remove('included', 'excluded');
    });
    
    (list.includeGenres || []).forEach(genreId => {
        const btn = document.querySelector(`#includeGenres .genre-btn[data-id="${genreId}"]`);
        if (btn) btn.classList.add('included');
    });
    
    (list.excludeGenres || []).forEach(genreId => {
        const btn = document.querySelector(`#excludeGenres .genre-btn[data-id="${genreId}"]`);
        if (btn) btn.classList.add('excluded');
    });
}

// Initialize everything
initLanguageButtons();
setupActorAutocomplete('actorSearch', 'autocomplete-list', null, false);
setupActorAutocomplete('excludeActorSearch', 'exclude-autocomplete-list', null, true);
setupStudioAutocomplete();
initGenreButtons();
showMainScreen();
loadLists();

// Backup and Restore functions
function backupData() {
    fetch('/api/backup')
        .then(r => r.blob())
        .then(blob => {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            const date = new Date().toISOString().split('T')[0];
            a.download = `flickarr-backup-${date}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        })
        .catch(err => alert('Backup failed: ' + err.message));
}

async function restoreData(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    if (!confirm('This will replace all current lists and cache. Continue?')) {
        event.target.value = '';
        return;
    }
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch('/api/restore', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success) {
            alert('Restore successful! Reloading...');
            location.reload();
        } else {
            alert('Restore failed: ' + result.error);
        }
    } catch (err) {
        alert('Restore failed: ' + err.message);
    }
    
    event.target.value = '';
          }
