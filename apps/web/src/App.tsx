import { useEffect, useState } from 'react';
import { readSystemStatus, type SystemStatus } from './status';

export default function App() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = setTimeout(() => controller.abort(), 6000);
    setLoading(true);
    setStatus(null);
    setError('');

    async function loadStatus() {
      try {
        const response = await fetch('/api/system/status', { signal: controller.signal });
        if (!response.ok) throw new Error(`API trả về HTTP ${response.status}.`);
        const result = readSystemStatus(await response.json());
        if (active) setStatus(result);
      } catch (cause) {
        if (active) setError(
          cause instanceof Error && cause.name !== 'AbortError'
            ? cause.message
            : 'API chưa phản hồi trong thời gian chờ.',
        );
      } finally {
        clearTimeout(timeout);
        if (active) setLoading(false);
      }
    }

    void loadStatus();
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  const services = [
    { name: 'API nghiệp vụ', detail: 'ASP.NET Core', ready: status ? true : null },
    { name: 'Cơ sở dữ liệu', detail: 'PostgreSQL · pgvector · Docker', ready: status ? status.database === 'ready' : null },
    { name: 'Dịch vụ AI', detail: 'FastAPI · thử nghiệm mô hình trên Google Colab', ready: status ? status.ai === 'ready' : null },
  ];

  return (
    <main>
      <header>
        <a className="brand" href="/" aria-label="Findie — trang khởi tạo">findie<span aria-hidden="true">.</span></a>
        <span className="environment">Môi trường phát triển</span>
      </header>

      <section className="intro" aria-labelledby="page-title">
        <p className="eyebrow">Nền tảng tìm và trao trả đồ thất lạc</p>
        <h1 id="page-title">Bắt đầu kết nối.</h1>
        <p className="lead">Cấu trúc dự án đã được khởi tạo. Trang này giúp kiểm tra kết nối giữa giao diện, API và các dịch vụ nền trước khi xây dựng nghiệp vụ.</p>
      </section>

      <section className="panel" aria-labelledby="services-title" aria-busy={loading}>
        <div className="panel-heading">
          <div>
            <h2 id="services-title">Trạng thái dịch vụ</h2>
            <p>Đọc trực tiếp từ API khi mở trang hoặc kiểm tra lại.</p>
          </div>
          <button type="button" disabled={loading} onClick={() => setAttempt((value) => value + 1)}>
            {loading ? 'Đang kiểm tra…' : 'Kiểm tra lại'}
          </button>
        </div>
        <div aria-live="polite" aria-atomic="true">
          {error && <p className="error" role="alert">Chưa đọc được trạng thái: {error} Hãy kiểm tra API cục bộ rồi thử lại.</p>}
          <ul className="services">
            {services.map((service) => (
              <li key={service.name}>
                <div><h3>{service.name}</h3><p>{service.detail}</p></div>
                <span className={`status ${service.ready === true ? 'ready' : service.ready === false ? 'unavailable' : 'unknown'}`}>
                  <span className="dot" aria-hidden="true" />
                  {loading ? 'Đang kiểm tra' : service.ready === true ? 'Sẵn sàng' : service.ready === false ? 'Chưa sẵn sàng' : 'Chưa xác định'}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="note">AI chưa sẵn sàng trong cấu hình hiện tại vì mô hình chỉ chạy thử trong Google Colab; FastAPI chưa thực hiện suy luận.</p>
      </section>

      <section className="next" aria-labelledby="scope-title">
        <h2 id="scope-title">Phạm vi hiện tại</h2>
        <p>Đăng tin, tìm kiếm, yêu cầu nhận đồ và hội thoại chưa được triển khai. Đăng nhập và lưu ảnh Cloudflare R2 cũng chưa được kết nối.</p>
        <p>Notebook Google Colab dùng để thử nghiệm Qwen và OpenCV trước khi tích hợp. Chưa sử dụng dữ liệu cá nhân thật trong giai đoạn này.</p>
      </section>
      <footer>Findie <span aria-hidden="true">/</span> Khởi tạo kỹ thuật</footer>
    </main>
  );
}
