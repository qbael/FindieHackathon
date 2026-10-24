import { useEffect, useState } from 'react';
import { loadUser, logout, type UserProfile } from './auth';
import { readSystemStatus, type SystemStatus } from './status';

export default function App() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    let active = true;
    setAuthLoading(true);
    setAuthError('');
    void loadUser(controller.signal).then((profile) => {
      if (active) setUser(profile);
    }).catch(() => {
      if (active) setAuthError('Chưa đọc được phiên đăng nhập. Hãy kiểm tra lại kết nối.');
    }).finally(() => {
      clearTimeout(timeout);
      if (active) setAuthLoading(false);
    });
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  async function handleLogout() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    setAuthLoading(true);
    setAuthError('');
    try {
      await logout(controller.signal);
      setUser(null);
    } catch (cause) {
      setAuthError(cause instanceof Error && cause.name !== 'AbortError'
        ? cause.message : 'Đăng xuất chưa hoàn tất trong thời gian chờ. Hãy thử lại.');
    } finally {
      clearTimeout(timeout);
      setAuthLoading(false);
    }
  }

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
        <p className="lead">Nền tảng xác thực và dữ liệu đã được khởi tạo. Trang này giúp kiểm tra kết nối giữa giao diện, API và các dịch vụ nền trước khi xây dựng nghiệp vụ.</p>
      </section>

      <section className="panel account" aria-labelledby="account-title" aria-busy={authLoading}>
        <div className="panel-heading">
          <div>
            <h2 id="account-title">{user ? `Xin chào, ${user.displayName}` : 'Đăng nhập Findie'}</h2>
            <p>{user ? user.email : 'Sử dụng tài khoản Google để tiếp tục.'}</p>
          </div>
          {user ? (
            <button type="button" disabled={authLoading} onClick={() => void handleLogout()}>
              {authLoading ? 'Đang xử lý…' : 'Đăng xuất'}
            </button>
          ) : !authLoading && status?.features.authentication ? (
            <a className="button" href="/api/auth/google?returnUrl=%2F">Đăng nhập bằng Google</a>
          ) : (
            <button type="button" disabled>
              {authLoading || loading ? 'Đang kiểm tra…' : 'Đăng nhập bằng Google'}
            </button>
          )}
        </div>
        <div aria-live="polite">
          {authError && <p className="error" role="alert">{authError}</p>}
          {!user && !loading && status?.features.authentication === false && (
            <p className="error">Đăng nhập Google chưa được cấu hình trên máy chủ.</p>
          )}
        </div>
      </section>

      <section className="panel" aria-labelledby="services-title" aria-busy={loading}>
        <div className="panel-heading">
          <div>
            <h2 id="services-title">Trạng thái dịch vụ</h2>
            <p>Đọc trực tiếp từ API khi mở trang hoặc kiểm tra lại.</p>
          </div>
          <button type="button" disabled={loading || authLoading} onClick={() => setAttempt((value) => value + 1)}>
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
        <p>Đăng nhập bằng Google, đăng xuất, hồ sơ cá nhân và API danh sách điểm tiếp nhận đã được triển khai.</p>
        <p>Đăng tin, tìm kiếm, yêu cầu nhận đồ, hội thoại và lưu ảnh Cloudflare R2 chưa được triển khai.</p>
        <p>Notebook Google Colab dùng để thử nghiệm Qwen và OpenCV trước khi tích hợp. Chưa sử dụng dữ liệu cá nhân thật trong giai đoạn này.</p>
      </section>
      <footer>Findie <span aria-hidden="true">/</span> Khởi tạo kỹ thuật</footer>
    </main>
  );
}
