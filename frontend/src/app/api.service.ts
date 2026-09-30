import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { AnalyzeRequest, Report, TestItem } from './report.model';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private base = '/api';

  listTests(): Observable<TestItem[]> {
    return this.http.get<TestItem[]>(`${this.base}/tests`);
  }

  getReport(id: string): Observable<Report> {
    return this.http.get<Report>(`${this.base}/analyses/${id}`);
  }

  listByTest(testId: string): Observable<any[]> {
    return this.http.get<any[]>(`${this.base}/analyses/by-test/${testId}`);
  }

  preview(body: AnalyzeRequest): Observable<any> {
    return this.http.post<any>(`${this.base}/analyses/elastic-preview`, body);
  }

  analyze(body: AnalyzeRequest): Observable<any> {
    return this.http.post<any>(`${this.base}/analyses`, body);
  }

  demoCase(name: 'clear_yield' | 'no_clear_yield' | 'missing_dims'): Observable<any> {
    return this.http.post<any>(`${this.base}/demo/synthetic/${name}`, {});
  }

  reportUrl(id: string): string {
    return `${this.base}/analyses/${id}/report`;
  }
}
