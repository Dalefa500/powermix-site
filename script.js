// Header shadow on scroll
const header = document.getElementById('header');
window.addEventListener('scroll', () => {
  header.classList.toggle('scrolled', window.scrollY > 10);
});

// Mobile menu toggle
const burger = document.getElementById('burger');
const mobileMenu = document.getElementById('mobileMenu');

burger.addEventListener('click', () => {
  burger.classList.toggle('active');
  mobileMenu.classList.toggle('open');
});

mobileMenu.querySelectorAll('a').forEach((link) => {
  link.addEventListener('click', () => {
    burger.classList.remove('active');
    mobileMenu.classList.remove('open');
  });
});

// Catalog filters
const filters = document.querySelectorAll('.filter');
const products = document.querySelectorAll('.product');

function applyFilter(filter) {
  products.forEach((product) => {
    const match = filter === 'all' || product.dataset.cat === filter;
    product.classList.toggle('show', match);
  });
}

filters.forEach((btn) => {
  btn.addEventListener('click', () => {
    filters.forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    applyFilter(btn.dataset.filter);
  });
});

applyFilter('all');

// Contact form (demo submit, no backend)
const form = document.getElementById('contactForm');
const formNote = document.getElementById('formNote');

form.addEventListener('submit', (e) => {
  e.preventDefault();
  formNote.textContent = 'Спасибо! Мы свяжемся с вами в ближайшее время.';
  form.reset();
});
