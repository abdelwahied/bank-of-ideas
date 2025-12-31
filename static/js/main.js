// تحديث السنة تلقائياً
document.addEventListener('DOMContentLoaded', function() {
    const currentYearElement = document.getElementById('current-year');
    if (currentYearElement) {
        currentYearElement.textContent = new Date().getFullYear();
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
                previewImage.style.cssText = 'width: 150px; height: 150px; object-fit: cover; border: 4px solid #3498db;';
                input.parentElement.parentElement.insertBefore(previewImage, input.parentElement);
            }
            
            previewImage.src = e.target.result;
        };
        reader.readAsDataURL(input.files[0]);
    }
}

