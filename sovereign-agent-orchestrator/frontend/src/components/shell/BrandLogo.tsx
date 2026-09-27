// The supplied logo is a black wordmark with a maroon monogram, which reads on the
// light theme and disappears on the dark one (#090a0c). So there are two baked
// variants -- the dark one recoloured to the theme's own foreground and accent -- and
// the swap is done in CSS off `:root[data-theme]` rather than in React, so the right
// one is painted on the first frame instead of after a context read.
type BrandLogoProps = { variant?: 'full' | 'mark'; className?: string }

function BrandLogo({ variant = 'full', className = '' }: BrandLogoProps) {
  const base = variant === 'full' ? 'logo' : 'mark'
  return (
    <span className={`brand-logo ${className}`}>
      <img src={`/brand/${base}-dark.png`} alt="Sovereign Operations / AI" className="brand-logo-dark" />
      <img src={`/brand/${base}-light.png`} alt="" aria-hidden="true" className="brand-logo-light" />
    </span>
  )
}

export default BrandLogo
