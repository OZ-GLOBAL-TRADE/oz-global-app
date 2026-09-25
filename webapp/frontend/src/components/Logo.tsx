import Image from "next/image";

/**
 * OZ Global Trade logosu. Logo lacivert/şeffaf olduğu için koyu arayüzde okunmaz; bu yüzden beyaz, yuvarlak köşeli bir
 * kart üzerinde gösterilir. `className` ile genişlik verin (yükseklik oranla ayarlanır).
 */
export default function Logo({ className = "w-48" }: { className?: string }) {
  return (
    <div className={`${className} rounded-lg bg-white px-3 py-2`}>
      <Image src="/logo.png" alt="OZ Global Trade" width={951} height={124} priority className="h-auto w-full" />
    </div>
  );
}
