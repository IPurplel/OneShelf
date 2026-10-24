import { useState, useCallback, useEffect, useRef } from "react";
import useEmblaCarousel from "embla-carousel-react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { CoverPlaceholder } from "@/components/CoverPlaceholder";
import { useI18n } from "@/i18n/i18n";

export type HeroSlide = {
  work_id: string | null;
  title: string;
  cover_url: string | null;
  description?: string | null;
  content_type?: string | null;
  label: string;
  fraction?: number | null;
};

export function HeroCarousel({ slides }: { slides: HeroSlide[] }) {
  const { language, t } = useI18n();
  const [emblaRef, emblaApi] = useEmblaCarousel({
    loop: slides.length > 1,
    direction: language === "ar" ? "rtl" : "ltr",
  });
  const [selectedIndex, setSelectedIndex] = useState(0);
  const autoplayRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopAutoplay = useCallback(() => {
    if (autoplayRef.current) {
      clearInterval(autoplayRef.current);
      autoplayRef.current = null;
    }
  }, []);

  const startAutoplay = useCallback(() => {
    stopAutoplay();
    if (!emblaApi || slides.length <= 1) return;
    autoplayRef.current = setInterval(() => emblaApi.scrollNext(), 6000);
  }, [emblaApi, slides.length, stopAutoplay]);

  const scrollPrev = useCallback(() => {
    emblaApi?.scrollPrev();
    stopAutoplay();
  }, [emblaApi, stopAutoplay]);

  const scrollNext = useCallback(() => {
    emblaApi?.scrollNext();
    stopAutoplay();
  }, [emblaApi, stopAutoplay]);

  useEffect(() => {
    if (!emblaApi) return;
    const onSelect = () => setSelectedIndex(emblaApi.selectedScrollSnap());
    emblaApi.on("select", onSelect);
    onSelect();
    startAutoplay();
    return () => {
      emblaApi.off("select", onSelect);
      stopAutoplay();
    };
  }, [emblaApi, startAutoplay, stopAutoplay]);

  if (slides.length === 0) return null;

  return (
    <div
      className="hero-carousel"
      onMouseEnter={stopAutoplay}
      onMouseLeave={startAutoplay}
      onFocusCapture={stopAutoplay}
      role="region"
      aria-roledescription="carousel"
      aria-label={slides[selectedIndex]?.title}
    >
      <div className="hero-carousel__viewport" ref={emblaRef}>
        <div className="hero-carousel__container">
          {slides.map((slide, index) => (
            <SlideCard key={slide.work_id ?? index} slide={slide} />
          ))}
        </div>
      </div>
      {slides.length > 1 && (
        <div className="hero-carousel__controls">
          <span className="hero-carousel__counter">
            {selectedIndex + 1} / {slides.length}
          </span>
          <button type="button" className="hero-carousel__arrow" onClick={scrollPrev} aria-label={t("hero.previousSlide")}>
            <ChevronLeft size={18} strokeWidth={2.2} aria-hidden="true" />
          </button>
          <button type="button" className="hero-carousel__arrow" onClick={scrollNext} aria-label={t("hero.nextSlide")}>
            <ChevronRight size={18} strokeWidth={2.2} aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}

function SlideCard({ slide }: { slide: HeroSlide }) {
  const [failedCover, setFailedCover] = useState<string | null>(null);
  const cover = slide.cover_url && slide.cover_url !== failedCover ? slide.cover_url : null;
  const percent = slide.fraction == null ? null : Math.round(slide.fraction * 100);

  return (
    <section className="hero hero-carousel__slide" role="group" aria-roledescription="slide" aria-label={slide.title}>
      {cover && <img className="hero__art" src={cover} alt="" aria-hidden="true" onError={() => setFailedCover(cover)} />}
      <div className="hero__inner">
        <span className="hero__cover" aria-hidden="true">
          {cover
            ? <img src={cover} alt="" onError={() => setFailedCover(cover)} />
            : <CoverPlaceholder title={slide.title} className="hero__blank workcard__blank" />}
        </span>
        <div className="hero__body">
          <p className="hero__reason">{slide.content_type ?? slide.label}</p>
          <h2 className="hero__title display" dir="auto">{slide.title}</h2>
          {slide.description && <p className="hero__description" dir="auto">{slide.description}</p>}
          {percent !== null && <p className="hero__progress">{`${percent}%`}</p>}
          {slide.work_id && (
            <Link className="button button--primary hero__action" to={`/works/${slide.work_id}`}>
              <span className="hero__play" aria-hidden="true">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor"><path d="M3 1.5 10 6l-7 4.5z" /></svg>
              </span>
              {slide.label}
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}
