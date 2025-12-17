// Telegram Web App API
const tg = window.Telegram.WebApp;

// Initialize app
tg.ready();
tg.expand();

// Set theme
tg.setHeaderColor('#215bee');
tg.setBackgroundColor('#ffffff');

// Get user data
const user = tg.initDataUnsafe.user || {
    id: 'demo',
    first_name: 'Demo',
    username: 'demo_user'
};

// API configuration
const API_URL = window.location.origin;

// State
let currentCategory = 'all';
let products = [];
let orders = [];
let categories = [];

// Initialize app
async function init() {
    console.log('Initializing app...', user);
    
    // Load data
    await Promise.all([
        loadProducts(),
        loadOrders(),
        loadProfile()
    ]);
    
    // Setup event listeners
    setupTabs();
    setupSearch();
}

// Load products
async function loadProducts() {
    try {
        const response = await fetch(`${API_URL}/api/products?user_id=${user.id}`);
        const data = await response.json();
        
        if (data.success) {
            products = data.products;
            categories = data.categories;
            
            renderCategories();
            renderProducts();
        }
    } catch (error) {
        console.error('Error loading products:', error);
        showError('Ошибка загрузки товаров');
    }
}

// Load orders
async function loadOrders() {
    try {
        const response = await fetch(`${API_URL}/api/orders?user_id=${user.id}`);
        const data = await response.json();
        
        if (data.success) {
            orders = data.orders;
            renderOrders();
        }
    } catch (error) {
        console.error('Error loading orders:', error);
        showError('Ошибка загрузки заказов');
    }
}

// Load profile
async function loadProfile() {
    try {
        const response = await fetch(`${API_URL}/api/profile?user_id=${user.id}`);
        const data = await response.json();
        
        if (data.success) {
            renderProfile(data.profile);
        }
    } catch (error) {
        console.error('Error loading profile:', error);
    }
}

// Render categories
function renderCategories() {
    const container = document.getElementById('categories-container');
    
    let html = '<button class="category-btn active" data-category="all" onclick="filterByCategory(\'all\')">Все</button>';
    
    categories.forEach(category => {
        html += `<button class="category-btn" data-category="${category}" onclick="filterByCategory('${category}')">${category}</button>`;
    });
    
    container.innerHTML = html;
}

// Render products
function renderProducts(filteredProducts = null) {
    const container = document.getElementById('products-container');
    const productsToRender = filteredProducts || products;
    
    if (productsToRender.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                <h3>Товары не найдены</h3>
                <p>Попробуйте изменить фильтры или поиск</p>
            </div>
        `;
        return;
    }
    
    let html = '';
    productsToRender.forEach(product => {
        const stockText = product.stock === null ? '∞ в наличии' : 
                         product.stock > 0 ? `${product.stock} шт.` : 'Нет в наличии';
        
        html += `
            <div class="product-card" onclick="openProductModal(${product.id})">
                <img src="${product.image || 'placeholder.png'}" alt="${product.name}" class="product-image" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 400 400%22%3E%3Crect fill=%22%23e8ecef%22 width=%22400%22 height=%22400%22/%3E%3Ctext x=%2250%25%22 y=%2250%25%22 dominant-baseline=%22middle%22 text-anchor=%22middle%22 font-family=%22monospace%22 font-size=%2240px%22 fill=%22%237f8c8d%22%3E${product.name.slice(0, 2).toUpperCase()}%3C/text%3E%3C/svg%3E'">
                <div class="product-info">
                    <div class="product-name">${product.name}</div>
                    <div class="product-price">${product.price}₽</div>
                    <div class="product-stock">${stockText}</div>
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

// Render orders
function renderOrders() {
    const container = document.getElementById('orders-container');
    
    if (orders.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                </svg>
                <h3>У вас пока нет заказов</h3>
                <p>Перейдите в магазин и сделайте первый заказ</p>
            </div>
        `;
        return;
    }
    
    let html = '';
    orders.forEach(order => {
        const statusClass = order.status === 'completed' ? 'completed' : 'pending';
        const statusText = order.status === 'completed' ? 'Завершен' : 'В обработке';
        const date = new Date(order.date).toLocaleDateString('ru-RU');
        
        html += `
            <div class="order-card">
                <div class="order-header">
                    <div class="order-id">Заказ #${order.id}</div>
                    <div class="order-status ${statusClass}">${statusText}</div>
                </div>
                <div class="order-info">
                    <div>${order.product_name}</div>
                    <div style="margin-top: 4px; font-size: 12px;">${date}</div>
                </div>
                <div class="order-price">${order.price}₽</div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

// Render profile
function renderProfile(profile) {
    document.getElementById('profile-name').textContent = user.first_name || 'Пользователь';
    document.getElementById('profile-username').textContent = user.username ? `@${user.username}` : '';
    document.getElementById('total-orders').textContent = profile.total_orders || 0;
    document.getElementById('total-spent').textContent = `${profile.total_spent || 0}₽`;
    
    // Set avatar
    const avatar = document.getElementById('profile-avatar');
    if (user.first_name) {
        avatar.textContent = user.first_name.charAt(0).toUpperCase();
    }
}

// Open product modal
function openProductModal(productId) {
    const product = products.find(p => p.id === productId);
    if (!product) return;
    
    const modal = document.getElementById('product-modal');
    const modalBody = document.getElementById('modal-body');
    
    const stockText = product.stock === null ? '∞ в наличии' : 
                     product.stock > 0 ? `${product.stock} шт. в наличии` : 'Нет в наличии';
    const canBuy = product.stock === null || product.stock > 0;
    
    modalBody.innerHTML = `
        <img src="${product.image || 'placeholder.png'}" alt="${product.name}" class="modal-product-image" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 400 250%22%3E%3Crect fill=%22%23e8ecef%22 width=%22400%22 height=%22250%22/%3E%3Ctext x=%2250%25%22 y=%2250%25%22 dominant-baseline=%22middle%22 text-anchor=%22middle%22 font-family=%22monospace%22 font-size=%2240px%22 fill=%22%237f8c8d%22%3E${product.name.slice(0, 2).toUpperCase()}%3C/text%3E%3C/svg%3E'">
        <h2 class="modal-product-name">${product.name}</h2>
        <p class="modal-product-description">${product.description || 'Описание отсутствует'}</p>
        <div style="color: #7f8c8d; margin-bottom: 16px;">${stockText}</div>
        <div class="modal-product-price">${product.price}₽</div>
        <button class="buy-btn" onclick="buyProduct(${product.id})" ${!canBuy ? 'disabled' : ''}>
            ${canBuy ? '🛒 Купить' : 'Нет в наличии'}
        </button>
    `;
    
    modal.classList.add('active');
    
    // Vibrate on open
    if (tg.HapticFeedback) {
        tg.HapticFeedback.impactOccurred('medium');
    }
}

// Close product modal
function closeProductModal() {
    const modal = document.getElementById('product-modal');
    modal.classList.remove('active');
}

// Buy product
async function buyProduct(productId) {
    const product = products.find(p => p.id === productId);
    if (!product) return;
    
    // Show confirmation
    tg.showConfirm(`Купить "${product.name}" за ${product.price}₽?`, async (confirmed) => {
        if (!confirmed) return;
        
        try {
            // Create order
            const response = await fetch(`${API_URL}/api/order`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    user_id: user.id,
                    product_id: productId,
                    init_data: tg.initData
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Close modal
                closeProductModal();
                
                // Show success
                tg.showAlert('✅ Заказ успешно создан!', () => {
                    // Reload orders
                    loadOrders();
                    loadProducts();
                });
                
                if (tg.HapticFeedback) {
                    tg.HapticFeedback.notificationOccurred('success');
                }
            } else {
                tg.showAlert(`❌ Ошибка: ${data.error}`);
                if (tg.HapticFeedback) {
                    tg.HapticFeedback.notificationOccurred('error');
                }
            }
        } catch (error) {
            console.error('Error creating order:', error);
            tg.showAlert('❌ Ошибка при создании заказа');
            if (tg.HapticFeedback) {
                tg.HapticFeedback.notificationOccurred('error');
            }
        }
    });
}

// Filter by category
function filterByCategory(category) {
    currentCategory = category;
    
    // Update active button
    document.querySelectorAll('.category-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.category === category) {
            btn.classList.add('active');
        }
    });
    
    // Filter products
    let filtered = products;
    if (category !== 'all') {
        filtered = products.filter(p => p.category === category);
    }
    
    // Apply search if active
    const searchValue = document.getElementById('search-input').value.toLowerCase();
    if (searchValue) {
        filtered = filtered.filter(p => 
            p.name.toLowerCase().includes(searchValue) ||
            (p.description && p.description.toLowerCase().includes(searchValue))
        );
    }
    
    renderProducts(filtered);
    
    if (tg.HapticFeedback) {
        tg.HapticFeedback.impactOccurred('light');
    }
}

// Setup tabs
function setupTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            
            // Update active tab
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            // Update active content
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            document.getElementById(`${tabName}-tab`).classList.add('active');
            
            if (tg.HapticFeedback) {
                tg.HapticFeedback.impactOccurred('light');
            }
        });
    });
}

// Setup search
function setupSearch() {
    const searchInput = document.getElementById('search-input');
    let searchTimeout;
    
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            const searchValue = e.target.value.toLowerCase();
            
            let filtered = products;
            
            // Apply category filter
            if (currentCategory !== 'all') {
                filtered = filtered.filter(p => p.category === currentCategory);
            }
            
            // Apply search filter
            if (searchValue) {
                filtered = filtered.filter(p => 
                    p.name.toLowerCase().includes(searchValue) ||
                    (p.description && p.description.toLowerCase().includes(searchValue))
                );
            }
            
            renderProducts(filtered);
        }, 300);
    });
}

// Open support
function openSupport() {
    tg.openTelegramLink('https://t.me/ecronx');
    if (tg.HapticFeedback) {
        tg.HapticFeedback.impactOccurred('medium');
    }
}

// Share app
function shareApp() {
    const shareText = 'Загляни в SharkOfBuy - крутой магазин в Telegram! 🦈';
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent('https://t.me/your_bot_username')}&text=${encodeURIComponent(shareText)}`;
    tg.openTelegramLink(shareUrl);
    
    if (tg.HapticFeedback) {
        tg.HapticFeedback.impactOccurred('medium');
    }
}

// Show error
function showError(message) {
    tg.showAlert(message);
}

// Close modal on background click
document.getElementById('product-modal').addEventListener('click', (e) => {
    if (e.target.id === 'product-modal') {
        closeProductModal();
    }
});

// Initialize on load
window.addEventListener('load', init);

