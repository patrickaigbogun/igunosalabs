document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('contact-form');
  if (!form) return;

  const statusEl = document.getElementById('form-status');
  const submitBtn = form.querySelector('button[type="submit"]');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = (form.querySelector('[name="email"]')?.value || '').trim();
    const project = (form.querySelector('[name="project"]')?.value || '').trim();

    if (!email) {
      statusEl.textContent = 'Please enter your email address.';
      statusEl.className = 'form-status err';
      return;
    }

    submitBtn.disabled = true;
    const origText = submitBtn.textContent;
    submitBtn.textContent = 'Sending...';
    statusEl.textContent = '';
    statusEl.className = 'form-status';

    try {
      const resp = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, project }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        throw new Error(data.error || 'Something went wrong.');
      }
      statusEl.textContent = 'Received. We will reach out to you shortly.';
      statusEl.className = 'form-status ok';
      form.reset();
    } catch (err) {
      statusEl.textContent = err.message || 'Could not send right now. Please try again.';
      statusEl.className = 'form-status err';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = origText;
    }
  });
});
