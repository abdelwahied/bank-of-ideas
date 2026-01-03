// تحديث السنة تلقائياً
document.addEventListener('DOMContentLoaded', function() {
    const currentYearElement = document.getElementById('current-year');
    if (currentYearElement) {
        currentYearElement.textContent = new Date().getFullYear();
    }
    
    // تحسين lazy loading للصور
    if ('loading' in HTMLImageElement.prototype) {
        // دعم native lazy loading
        const images = document.querySelectorAll('img[loading="lazy"]');
        images.forEach(img => {
            img.addEventListener('load', function() {
                this.classList.add('loaded');
            });
        });
    } else {
        // fallback للمتصفحات القديمة باستخدام Intersection Observer
        const images = document.querySelectorAll('img[loading="lazy"]');
        const imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    img.src = img.dataset.src || img.src;
                    img.classList.add('loaded');
                    observer.unobserve(img);
                }
            });
        });
        
        images.forEach(img => imageObserver.observe(img));
    }
});

// معاينة الصورة قبل الرفع
function previewImage(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const previewPlaceholder = document.getElementById('preview-placeholder');
            let previewImage = document.getElementById('preview-image');
            
            if (previewPlaceholder) {
                previewPlaceholder.style.display = 'none';
            }
            
            if (!previewImage) {
                previewImage = document.createElement('img');
                previewImage.id = 'preview-image';
                previewImage.className = 'rounded-circle mb-3';
                previewImage.width = 150;
                previewImage.height = 150;
                previewImage.style.cssText = 'width: 150px; height: 150px; object-fit: cover; border: 4px solid #3498db;';
                input.parentElement.parentElement.insertBefore(previewImage, input.parentElement);
            }
            
            previewImage.src = e.target.result;
        };
        reader.readAsDataURL(input.files[0]);
    }
}
